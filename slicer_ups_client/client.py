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


class UPSClient:
    def __init__(self, transport: DicomwebClient | str, token: Optional[str] = None) -> None:
        if isinstance(transport, str):
            transport = DicomwebClient(transport, token=token)
        self._web: DicomwebClient = transport
        self.watcher = Watcher(transport)

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
        """PUT /workitems/{uid} (11.6). Attributes incl. (0074,1210) are only
        modifiable while the workitem is SCHEDULED."""
        self._web.put(f"/workitems/{workitem_uid}", body=patch)
        return self.get(workitem_uid)

    def claim(self, workitem_uid: str) -> Workitem:
        """Transition to IN PROGRESS (RAD-55)."""
        return self.change_state(workitem_uid, STATE_IN_PROGRESS)

    def change_state(self, workitem_uid: str, state: str, reason: Optional[str] = None) -> Workitem:
        """PUT /workitems/{uid}/state (11.7), Transaction UID from the current
        workitem. CANCELED carries Reason For Cancellation (0074,1238) LT."""
        current = self.get(workitem_uid)
        tx_uid = get_string(current.raw, TRANSACTION_UID)
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
        (0040,4033) over WADO-RS into a temp directory. Returns the paths."""
        workitem = self.get(workitem_uid)
        output_seq = workitem.raw.get(OUTPUT_INFORMATION_SEQUENCE, {})
        items = output_seq.get("Value", []) if isinstance(output_seq, dict) else []
        tmp = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="slicer-ups-"))
        paths: list[Path] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            study = get_string(item, STUDY_INSTANCE_UID)
            series_seq = item.get(REFERENCED_SERIES_SEQUENCE, {})
            series_items = series_seq.get("Value", []) if isinstance(series_seq, dict) else []
            for series in series_items:
                if not isinstance(series, dict):
                    continue
                series_uid = get_string(series, SERIES_INSTANCE_UID)
                sop_seq = series.get(REFERENCED_SOP_SEQUENCE, {})
                sop_items = sop_seq.get("Value", []) if isinstance(sop_seq, dict) else []
                for sop in sop_items:
                    if not isinstance(sop, dict):
                        continue
                    instance_uid = get_string(sop, REFERENCED_SOP_INSTANCE_UID)
                    if not (study and series_uid and instance_uid):
                        continue
                    path = tmp / f"{instance_uid}.dcm"
                    data = self._web.request(
                        "GET",
                        f"/studies/{study}/series/{series_uid}/instances/{instance_uid}",
                        raw=True,
                    )
                    path.write_bytes(data.content)
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
        return body


__all__ = [
    "UPSClient",
    "Workitem",
    "WorkitemEvent",
    "WorkitemParameter",
    "Code",
    "parse_event",
]
