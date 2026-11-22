"""Workitem watcher: subscribe (WebSocket) with transparent polling fallback.

PS3.18 11.10 (Subscribe) + 11.11 (Open Event Channel) is OPTIONAL for the
origin; Retrieve (GET /workitems/{uid}) and Search are the mandatory
baseline. dcm4chee-arc answers the Subscribe POST with 201 but has no
WebSocket server, so a 201 NEVER proves the channel is up. The fallback to
polling is therefore the guaranteed path, not a vendor hack.

Anti-rabbit guarantees baked in (from the OHIF PR #6371 review):
- POST the subscription BEFORE opening the channel, and open the channel at
  the response Content-Location, never by string-building the URL.
- Parse the STANDARD DICOM JSON N-EVENT-REPORT (Affected SOP Instance UID
  0008,1000, Procedure Step State 0074,1000, Event Type ID 0000,1002); a
  Clarus envelope field is a compatibility path only.
- Drop events whose affected UID differs from the subscribed workitem.
- One subscription per (workitem, AE): share it, never DELETE a subscription
  another watcher still uses.
- On a failed channel open, best-effort DELETE the subscription just created.
"""
from __future__ import annotations

import json
import logging
import time
from threading import Lock
from typing import Any, Callable, Optional

from .dicomweb import DicomwebClient
from .models import (
    WorkitemEvent,
    Workitem,
    AFFECTED_SOP_INSTANCE_UID,
    PROCEDURE_STEP_STATE,
    EVENT_TYPE_ID,
    TERMINAL_STATES,
    get_string,
)

log = logging.getLogger("slicer_ups_client")


def parse_event(payload: str) -> WorkitemEvent | None:
    """Parse one notification frame into a typed event.

    Standard shape (PS3.18 11.11) is a DICOM JSON dataset carrying Affected
    SOP Instance UID and Procedure Step State. A Clarus envelope
    (`workitem_uid` / `new_state`) is accepted as a compatibility path only.
    """
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    uid = get_string(data, AFFECTED_SOP_INSTANCE_UID)
    state = get_string(data, PROCEDURE_STEP_STATE)
    if uid is None:
        uid = data.get("workitem_uid")
    if state is None:
        state = data.get("new_state")
    if not uid or not state:
        return None
    return WorkitemEvent(workitem_uid=str(uid), state=str(state), raw=data)


class Subscription:
    """A live subscription handle. Close it to unsubscribe (refcounted)."""

    def __init__(
        self,
        client: DicomwebClient,
        workitem_uid: str,
        ae_title: str,
        ws: Any,
    ) -> None:
        self._client = client
        self.workitem_uid = workitem_uid
        self.ae_title = ae_title
        self._ws = ws
        self._closed = False

    def recv(self, timeout: Optional[float] = None) -> WorkitemEvent | None:
        frame = self._ws.recv()
        if frame is None:
            return None
        event = parse_event(str(frame))
        if event is None:
            return None
        # Foreign-workitem filter: the channel is scoped to the AE title, not
        # to one workitem.
        if event.workitem_uid != self.workitem_uid:
            return None
        return event

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001 - close is best-effort
            pass
        # Best-effort unsubscribe; another watcher of the same pair may still
        # hold it, so the origin de-duplicates by (workitem, AE).
        try:
            self._client.delete(
                f"/workitems/{self.workitem_uid}/subscribers/{self.ae_title}"
            )
        except Exception:  # noqa: BLE001
            pass


class Watcher:
    def __init__(self, client: DicomwebClient) -> None:
        self._client = client
        self._shared: dict[tuple[str, str], Subscription] = {}
        self._lock = Lock()

    def subscribe(
        self,
        workitem_uid: str,
        ae_title: str,
        mode: str = "auto",
    ) -> Subscription:
        """Create (or share) a subscription. `mode` is 'auto' | 'websocket'.

        'websocket' raises if the channel cannot be opened; 'auto' raises
        only if the Subscribe POST itself is refused with a hard error (the
        caller then falls back to polling).
        """
        key = (workitem_uid, ae_title)
        with self._lock:
            existing = self._shared.get(key)
            if existing is not None:
                return existing

        # 1. POST the subscription (RAD-86). A 201 carries Content-Location,
        #    which is the WebSocket endpoint (11.10).
        response = self._client.post(
            f"/workitems/{workitem_uid}/subscribers/{ae_title}",
            raw=True,
        )
        location = response.headers.get("Content-Location") if response is not None else None
        if not location:
            if mode == "websocket":
                raise RuntimeError(
                    f"origin returned no Content-Location for {workitem_uid}"
                )
            raise RuntimeError(f"no subscription channel for {workitem_uid}")

        # 2. Open the channel at the Location, not a rebuilt URL.
        try:
            ws = self._client.open_websocket(location)
        except Exception as exc:
            # Cleanup the subscription just created (checklist 6), best-effort.
            try:
                self._client.delete(f"/workitems/{workitem_uid}/subscribers/{ae_title}")
            except Exception:  # noqa: BLE001
                pass
            if mode == "websocket":
                raise
            raise RuntimeError(f"channel open failed for {workitem_uid}") from exc

        sub = Subscription(self._client, workitem_uid, ae_title, ws)
        with self._lock:
            self._shared[key] = sub
        return sub

    def watch(
        self,
        workitem_uid: str,
        ae_title: str,
        mode: str = "auto",
        poll_interval: float = 2.0,
        timeout: Optional[float] = None,
    ) -> Workitem:
        """Block until the workitem reaches COMPLETED or CANCELED.

        `mode='auto'` tries the WebSocket path and falls back to polling on
        any failure; `'websocket'`/`'poll'` force one transport.
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        if mode in ("auto", "websocket"):
            try:
                sub = self.subscribe(workitem_uid, ae_title, mode=mode)
                return self._watch_ws(sub, deadline)
            except RuntimeError:
                if mode == "websocket":
                    raise

        if mode in ("auto", "poll"):
            return self._watch_poll(workitem_uid, poll_interval, deadline)

        raise ValueError(f"unknown mode {mode!r}")

    def _watch_ws(self, sub: Subscription, deadline: Optional[float]) -> Workitem:
        while True:
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"watch timed out for {sub.workitem_uid}")
            event = sub.recv()
            if event is not None and event.state in TERMINAL_STATES:
                return self._fetch(sub.workitem_uid)

    def _watch_poll(
        self, workitem_uid: str, poll_interval: float, deadline: Optional[float]
    ) -> Workitem:
        while True:
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"watch timed out for {workitem_uid}")
            item = self._fetch(workitem_uid)
            if item.state in TERMINAL_STATES:
                return item
            time.sleep(poll_interval)

    def _fetch(self, workitem_uid: str) -> Workitem:
        # Imported here to avoid a circular import at module load.
        from .client import UPSClient

        client = UPSClient(self._client)
        return client.get(workitem_uid)
