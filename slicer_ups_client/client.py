"""UPSClient: a CLI-first, UI-agnostic UPS-RS client (PS3.18 section 11).

The public surface mirrors the dwv/OHIF UPS user agents, so the same contract
works from Slicer, Weasis, OHIF and a CLI unchanged. High-level helpers
(`run`, `cancel`, `watch`, `download_outputs`) sit on the low-level
transactions, and task parameters are passed through (0074,1210) from day one.
"""
from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .dicomweb import DicomwebClient, encode_query
from .models import (
    Code,
    Workitem,
    WorkitemEvent,
    WorkitemParameter,
    MODALITY,
    SOP_INSTANCE_UID,
    STUDY_INSTANCE_UID,
    SERIES_INSTANCE_UID,
    REQUESTED_PROCEDURE_ID,
    SCHEDULED_WORKITEM_CODE_SEQUENCE,
    SCHEDULED_STATION_NAME_CODE_SEQUENCE,
    INPUT_INFORMATION_SEQUENCE,
    OUTPUT_INFORMATION_SEQUENCE,
    REFERENCED_SERIES_SEQUENCE,
    REFERENCED_SOP_SEQUENCE,
    REFERENCED_SOP_INSTANCE_UID,
    TRANSACTION_UID,
    REASON_FOR_CANCELLATION,
    PROCEDURE_STEP_STATE,
    STATE_IN_PROGRESS,
    STATE_CANCELED,
    STATE_SCHEDULED,
    SCHEDULED_PROCEDURE_STEP_PRIORITY,
    PROCEDURE_STEP_LABEL,
    SCHEDULED_PROCEDURE_STEP_START_DATETIME,
    INPUT_READINESS_STATE,
    new_workitem_uid,
    get_string,
    get_first_item,
)
from .parameters import encode_parameters, decode_parameters
from .watcher import Watcher, parse_event

log = logging.getLogger("slicer_ups_client")


def _dicom_part(content_type: Optional[str], body: bytes) -> bytes:
    """The DICOM bytes of a WADO-RS instance response.

    The default representation is multipart/related (PS3.18 10.4.4);
    single-part application/dicom is optional. A non-multipart body is
    returned unchanged. A multipart body has exactly one part for a single
    instance retrieve: `--boundary`, the part headers, then the DICOM bytes
    before the closing `--boundary--`. The closing delimiter is recognised
    only when it begins a line (a CRLF precedes it); the payload slice keeps
    every byte it carries.
    """
    if not content_type or not content_type.lower().startswith("multipart"):
        return body
    boundary: Optional[str] = None
    for piece in content_type.split(";"):
        piece = piece.strip()
        if piece.lower().startswith("boundary="):
            boundary = piece.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not boundary:
        return body
    delimiter = ("--" + boundary).encode("utf-8")
    start = body.find(delimiter)
    if start == -1:
        return body
    header_end = body.find(b"\r\n\r\n", start)
    if header_end == -1:
        return body
    payload_start = header_end + 4
    # A delimiter closes the part only when it begins a line (a CRLF precedes
    # it). Searching for the CRLF-prefixed form preserves a boundary-like run
    # inside the payload, and the slice keeps every trailing byte the payload
    # carries - the framing CRLF belongs to the delimiter, outside the slice.
    end = body.find(b"\r\n" + delimiter, payload_start)
    if end == -1:
        return body[payload_start:]
    return body[payload_start:end]


class UPSClient:
    def __init__(self, transport: DicomwebClient | str, token: Optional[str] = None) -> None:
        if isinstance(transport, str):
            transport = DicomwebClient(transport, token=token)
        self._web: DicomwebClient = transport
        self.watcher = Watcher(transport)
        # PS3.18 11.5.2 forbids GET from returning the Transaction UID, so a
        # claim the client itself installs has no other home: the UID the
        # client generated is retained here per workitem and reused by later
        # update/change_state calls.
        self._transaction_uids: dict[str, str] = {}

    # -- low-level transactions -------------------------------------------
    def search(self, filters: dict) -> list[Workitem]:
        """GET /workitems (11.9). 204 = empty list, never an error."""
        raw = self._web.get("/workitems", params=encode_query(filters))
        if raw is None:
            return []  # 204 No Content: zero matches
        if isinstance(raw, dict):
            raw = [raw]
        return [self._to_workitem(item) for item in raw]

    def get(self, workitem_uid: str) -> Workitem:
        raw = self._web.get(f"/workitems/{workitem_uid}")
        if raw is None:
            raise LookupError(f"workitem {workitem_uid} not found")
        return self._to_workitem(raw)

    def create(
        self,
        workitem: dict,
        parameters: Optional[list[WorkitemParameter]] = None,
    ) -> str:
        """POST /workitems?workitem={uid} (PS3.18 11.4). Returns the new UID.

        The Workitem UID is the `workitem` query parameter (the Affected SOP
        Instance UID); the SOP Class UID is set by the SCP, so neither belongs
        in the body.
        """
        uid = new_workitem_uid()
        body = dict(workitem)
        if parameters:
            body.update(encode_parameters(parameters))
        response = self._web.request(
            "POST", "/workitems", params={"workitem": uid}, json=body, raw=True
        )
        location = response.headers.get("Content-Location") if response is not None else None
        if location:
            return location.rstrip("/").rsplit("/", 1)[-1]
        return uid

    def update(self, workitem_uid: str, patch: dict) -> Workitem:
        """POST /workitems/{uid}?TransactionUid={tx} (11.6). Attributes incl.
        (0074,1210) are only modifiable while the workitem is SCHEDULED.

        The Transaction UID rides on BOTH carriages the standard gives it:
        the `?TransactionUid=` query parameter (11.6.1.2) and the (0008,1195)
        data-set attribute (CC.2.6.2). A SCHEDULED workitem has no lock yet,
        so both are omitted then.
        """
        current = self.get(workitem_uid)
        tx_uid = None
        if current.state != STATE_SCHEDULED:
            tx_uid = get_string(current.raw, TRANSACTION_UID) or self._transaction_uids.get(workitem_uid)
        body = dict(patch)
        if tx_uid:
            body[TRANSACTION_UID] = {"vr": "UI", "Value": [tx_uid]}
        params = {"TransactionUid": tx_uid} if tx_uid else None
        self._web.request(
            "POST", f"/workitems/{workitem_uid}", params=params, json=body
        )
        return self.get(workitem_uid)

    def claim(self, workitem_uid: str) -> Workitem:
        """Transition to IN PROGRESS (RAD-55)."""
        return self.change_state(workitem_uid, STATE_IN_PROGRESS)

    def change_state(self, workitem_uid: str, state: str, reason: Optional[str] = None) -> Workitem:
        """PUT /workitems/{uid}/state (11.7). The Transaction UID travels in the
        data set (CC.2.1-1); a claim (SCHEDULED -> IN PROGRESS) installs a new
        one because a queued workitem carries no lock yet. CANCELED carries
        Reason For Cancellation (0074,1238) LT."""
        current = self.get(workitem_uid)
        tx_uid = get_string(current.raw, TRANSACTION_UID) or self._transaction_uids.get(workitem_uid)
        if state == STATE_IN_PROGRESS and not tx_uid:
            tx_uid = new_workitem_uid()
        if tx_uid:
            # Retain BEFORE the write: if the write or the readback raises,
            # the UID the client owns must survive for the next attempt.
            self._transaction_uids[workitem_uid] = tx_uid
        body: dict[str, dict] = {PROCEDURE_STEP_STATE: {"vr": "CS", "Value": [state]}}
        if tx_uid:
            body[TRANSACTION_UID] = {"vr": "UI", "Value": [tx_uid]}
        if state == STATE_CANCELED:
            body[REASON_FOR_CANCELLATION] = {"vr": "LT", "Value": [reason or "canceled by requester"]}
        self._web.put(f"/workitems/{workitem_uid}/state", body=body)
        return self.get(workitem_uid)

    def subscribe(
        self,
        workitem_uid: str,
        ae_title: str,
        mode: str = "auto",
    ):
        return self.watcher.subscribe(workitem_uid, ae_title, mode=mode)

    # -- high-level helpers ------------------------------------------------
    def run(
        self,
        study_uid: str,
        code: Code,
        params: Optional[list[WorkitemParameter]] = None,
        *,
        modality: str = "CT",
        series_uid: Optional[str] = None,
        requested_procedure_id: Optional[str] = None,
        station: Optional[str] = None,
        ae_title: str = "SLICERUPS",
        watch_mode: str = "auto",
        poll_interval: float = 2.0,
        timeout: Optional[float] = None,
    ) -> str:
        """Create a workitem for the study, then wait until it completes.

        Returns the workitem UID. Call `download_outputs` on it afterwards.
        """
        workitem = self._build_workitem(
            study_uid=study_uid,
            code=code,
            modality=modality,
            series_uid=series_uid,
            requested_procedure_id=requested_procedure_id,
            station=station,
        )
        uid = self.create(workitem, parameters=params)
        self.watcher.watch(
            uid,
            ae_title,
            mode=watch_mode,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        return uid

    def cancel(self, workitem_uid: str, reason: Optional[str] = None) -> None:
        self.change_state(workitem_uid, STATE_CANCELED, reason=reason)

    def watch(
        self,
        workitem_uid: str,
        mode: str = "auto",
        poll_interval: float = 2.0,
        timeout: Optional[float] = None,
        ae_title: str = "SLICERUPS",
    ) -> Workitem:
        return self.watcher.watch(
            workitem_uid,
            ae_title,
            mode=mode,
            poll_interval=poll_interval,
            timeout=timeout,
        )

    def download_outputs(self, workitem_uid: str, out_dir: Optional[Path] = None) -> list[Path]:
        """Retrieve the result instances named by Output Information Sequence
        (0040,4033) over WADO-RS into a temp directory. Returns the paths.

        (0040,4033) is a child of (0074,1216) Unified Procedure Step Performed
        Procedure Sequence (PS3.3 C.30.3-1), not a top-level attribute. Each
        item carries the Referenced Instances and Access Macro (PS3.3 Table
        10-3b): a flat (0008,1150)/(0008,1155) pair, or a nested (0008,1199)
        Referenced SOP Sequence, plus (0020,000D)/(0020,000E) at the item
        level. The study UID falls back to the workitem's own when an item
        omits it.
        """
        workitem = self.get(workitem_uid)
        performed = get_first_item(workitem.raw, "00741216") or {}
        output_seq = performed.get(OUTPUT_INFORMATION_SEQUENCE, {})
        items = output_seq.get("Value", []) if isinstance(output_seq, dict) else []
        study = get_string(workitem.raw, STUDY_INSTANCE_UID)
        if not study:
            study = get_string(
                get_first_item(workitem.raw, INPUT_INFORMATION_SEQUENCE) or {},
                STUDY_INSTANCE_UID,
            )
        tmp = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="slicer-ups-"))
        tmp.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_study = get_string(item, STUDY_INSTANCE_UID) or study
            series_uid = get_string(item, SERIES_INSTANCE_UID)
            nested = item.get(REFERENCED_SOP_SEQUENCE, {})
            sop_items = (
                nested.get("Value", [])
                if isinstance(nested, dict) and isinstance(nested.get("Value"), list)
                else [item]
            )
            for sop in sop_items:
                if not isinstance(sop, dict):
                    continue
                instance_uid = get_string(sop, REFERENCED_SOP_INSTANCE_UID)
                if not (item_study and series_uid and instance_uid):
                    continue
                path = tmp / f"{instance_uid}.dcm"
                data = self._web.request(
                    "GET",
                    f"/studies/{item_study}/series/{series_uid}/instances/{instance_uid}",
                    raw=True,
                    accept='multipart/related; type="application/dicom"',
                )
                content_type = data.headers.get("Content-Type", "") if data.headers else ""
                path.write_bytes(_dicom_part(content_type, data.content))
                paths.append(path)
        return paths

    # -- internals ---------------------------------------------------------
    def _to_workitem(self, raw: dict) -> Workitem:
        uid = get_string(raw, SOP_INSTANCE_UID) or ""
        state = get_string(raw, PROCEDURE_STEP_STATE) or ""
        return Workitem(uid=uid, state=state, raw=raw, parameters=decode_parameters(raw))

    def _build_workitem(
        self,
        *,
        study_uid: str,
        code: Code,
        modality: str,
        series_uid: Optional[str],
        requested_procedure_id: Optional[str],
        station: Optional[str] = None,
    ) -> dict:
        body: dict[str, dict] = {
            MODALITY: {"vr": "CS", "Value": [modality]},
            STUDY_INSTANCE_UID: {"vr": "UI", "Value": [study_uid]},
            SCHEDULED_WORKITEM_CODE_SEQUENCE: {"vr": "SQ", "Value": [code.to_json()]},
            # Type-1 at N-CREATE (PS3.4 Table CC.2.5-3): the SCP must not
            # invent these, and a conformant origin refuses a body without them.
            SCHEDULED_PROCEDURE_STEP_PRIORITY: {"vr": "CS", "Value": ["MEDIUM"]},
            PROCEDURE_STEP_LABEL: {"vr": "SH", "Value": [code.meaning or code.value]},
            SCHEDULED_PROCEDURE_STEP_START_DATETIME: {
                "vr": "DT",
                "Value": [datetime.now().strftime("%Y%m%d%H%M%S")],
            },
            INPUT_READINESS_STATE: {"vr": "CS", "Value": ["READY"]},
        }
        if requested_procedure_id:
            body[REQUESTED_PROCEDURE_ID] = {"vr": "SH", "Value": [requested_procedure_id]}
        input_item: dict[str, dict] = {STUDY_INSTANCE_UID: {"vr": "UI", "Value": [study_uid]}}
        if series_uid:
            input_item[REFERENCED_SERIES_SEQUENCE] = {
                "vr": "SQ",
                "Value": [{SERIES_INSTANCE_UID: {"vr": "UI", "Value": [series_uid]}}],
            }
        body[INPUT_INFORMATION_SEQUENCE] = {"vr": "SQ", "Value": [input_item]}
        if station:
            body[SCHEDULED_STATION_NAME_CODE_SEQUENCE] = {
                "vr": "SQ",
                "Value": [
                    Code(value=station, scheme="99CLARUS", meaning=station).to_json()
                ],
            }
        return body


__all__ = [
    "UPSClient",
    "Workitem",
    "WorkitemEvent",
    "WorkitemParameter",
    "Code",
    "parse_event",
]
