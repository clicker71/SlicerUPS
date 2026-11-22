"""Anti-rabbit tests for the UPSClient and Watcher.

Each test pins one of the behaviours CodeRabbit flagged on the OHIF UPS
client. A test that stays green with the fix reverted is vacuous and is not
shipped here - so each test drives the real code path.
"""

import pytest

from slicer_ups_client import UPSClient, Code, parse_event
from slicer_ups_client.watcher import Subscription


class FakeResponse:
    def __init__(self, headers=None, status_code=200):
        self.headers = headers or {}
        self.status_code = status_code
        self.reason = "OK"
        self.content = b""


class FakeWebSocket:
    def __init__(self, frames):
        self._frames = list(frames)

    def recv(self):
        return self._frames.pop(0) if self._frames else None

    def close(self):
        pass


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.get_result = None
        self.post_result = FakeResponse()
        self.websocket = None
        self.open_raises = None

    def get(self, path, params=None):
        self.calls.append(("get", path))
        return self.get_result

    def post(self, path, body=None, raw=False):
        self.calls.append(("post", path))
        return self.post_result

    def put(self, path, body=None, raw=False):
        self.calls.append(("put", path))
        self.last_json = body
        return self.post_result

    def delete(self, path):
        self.calls.append(("delete", path))
        return self.post_result

    def request(self, method, path, *, params=None, json=None, raw=False, accept=None):
        self.calls.append((method, path, params))
        self.last_json = json
        self.last_accept = accept
        return self.post_result

    def open_websocket(self, url, timeout=None):
        self.calls.append(("ws", url))
        if self.open_raises is not None:
            raise self.open_raises
        return self.websocket


WORKITEM_COMPLETED = {
    "00080018": {"vr": "UI", "Value": ["1.2.3"]},
    "00741000": {"vr": "CS", "Value": ["COMPLETED"]},
}


def test_search_204_is_an_empty_list_not_an_error():
    t = FakeTransport()
    t.get_result = None  # 204 No Content
    items = UPSClient(t).search({})
    assert items == []
    assert t.calls == [("get", "/workitems")]


def test_search_rows_become_workitems():
    t = FakeTransport()
    t.get_result = [WORKITEM_COMPLETED]
    items = UPSClient(t).search({})
    assert len(items) == 1
    assert items[0].uid == "1.2.3" and items[0].state == "COMPLETED"


def test_subscribe_posts_before_opening_channel():
    t = FakeTransport()
    t.post_result = FakeResponse(headers={"Content-Location": "ws://origin/ws/1"})
    t.websocket = FakeWebSocket([])
    UPSClient(t).watcher.subscribe("1.2.3", "AE", mode="websocket")
    # The POST must come before the WebSocket open, and the open must use the
    # returned Location, not a rebuilt URL.
    assert t.calls[0] == ("post", "/workitems/1.2.3/subscribers/AE")
    assert t.calls[1] == ("ws", "ws://origin/ws/1")


def test_watch_falls_back_to_polling_when_channel_open_fails():
    t = FakeTransport()
    t.post_result = FakeResponse(headers={"Content-Location": "ws://origin/ws/1"})
    t.open_raises = RuntimeError("no ws")
    t.get_result = WORKITEM_COMPLETED
    item = UPSClient(t).watch("1.2.3", mode="auto", poll_interval=0.0)
    assert item.state == "COMPLETED"
    # A failed open must clean up the subscription, then poll via GET.
    assert ("delete", "/workitems/1.2.3/subscribers/SLICERUPS") in t.calls
    assert ("get", "/workitems/1.2.3") in t.calls


def test_parse_event_standard_dicom_json():
    payload = (
        '{"00081000":{"vr":"UI","Value":["1.2.3"]},'
        '"00741000":{"vr":"CS","Value":["COMPLETED"]}}'
    )
    event = parse_event(payload)
    assert event is not None
    assert event.workitem_uid == "1.2.3" and event.state == "COMPLETED"


def test_create_sends_workitem_query_and_no_sop_class():
    t = FakeTransport()
    t.post_result = FakeResponse(
        headers={"Content-Location": "http://origin/dicomweb/workitems/2.25.999"}
    )
    uid = UPSClient(t).create(
        {"0020000D": {"vr": "UI", "Value": ["1.2.3"]}},
    )
    assert uid == "2.25.999"
    method, path, params = t.calls[0]
    assert (method, path) == ("POST", "/workitems")
    assert set(params) == {"workitem"}
    assert params["workitem"].startswith("2.25.")
    # SOP Class UID and SOP Instance UID must not be in the body: the UID is
    # the query parameter and the SOP Class is set by the SCP.
    assert "00080016" not in t.last_json
    assert "00080018" not in t.last_json


def test_build_workitem_has_type1_create_attributes():
    cl = UPSClient(FakeTransport())
    wi = cl._build_workitem(
        study_uid="1.2.3",
        code=Code("CXR-AI", "99CLARUS"),
        modality="DX",
        series_uid=None,
        requested_procedure_id=None,
    )
    assert wi["00741200"]["Value"] == ["MEDIUM"]
    assert wi["00741204"]["Value"] == ["CXR-AI"]
    assert wi["00404041"]["Value"] == ["READY"]
    start = wi["00404005"]["Value"][0]
    assert len(start) == 14 and start.isdigit()
    assert "00080016" not in wi
    assert "00080018" not in wi


def test_parse_event_clarus_envelope_compatibility():
    event = parse_event('{"workitem_uid":"1.2.3","new_state":"COMPLETED"}')
    assert event is not None and event.workitem_uid == "1.2.3"


def test_foreign_workitem_event_is_dropped():
    t = FakeTransport()
    t.post_result = FakeResponse(headers={"Content-Location": "ws://origin/ws/1"})
    t.websocket = FakeWebSocket(
        ['{"00081000":{"vr":"UI","Value":["9.9.9"]},"00741000":{"vr":"CS","Value":["COMPLETED"]}}']
    )
    sub = Subscription(t, "1.2.3", "AE", t.websocket)
    # The frame names a different workitem; recv must drop it (return None).
    assert sub.recv() is None


def test_reverted_subscribe_order_would_fail():
    # The fixed code opens the channel at Content-Location. If the order were
    # inverted (no POST before open), the call log would not lead with POST.
    t = FakeTransport()
    t.post_result = FakeResponse(headers={"Content-Location": "ws://origin/ws/1"})
    t.websocket = FakeWebSocket([])
    UPSClient(t).watcher.subscribe("1.2.3", "AE", mode="websocket")
    assert t.calls[0][0] == "post"
    assert t.calls[1][0] == "ws"


WORKITEM_IN_PROGRESS_LOCKED = {
    "00080018": {"vr": "UI", "Value": ["2.25.9"]},
    "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
    "00081195": {"vr": "UI", "Value": ["2.25.77"]},
}


def test_update_posts_with_transaction_uid_on_both_carriages():
    t = FakeTransport()
    t.get_result = WORKITEM_IN_PROGRESS_LOCKED
    UPSClient(t).update("2.25.9", {"00741204": {"vr": "SH", "Value": ["retuned"]}})
    method, path, params = t.calls[1]  # calls[0] is the get of the current workitem
    assert method == "POST"
    assert path == "/workitems/2.25.9"
    assert params == {"TransactionUid": "2.25.77"}
    assert t.last_json["00081195"] == {"vr": "UI", "Value": ["2.25.77"]}
    assert t.last_json["00741204"]["Value"] == ["retuned"]


def test_update_scheduled_workitem_omits_the_transaction_uid():
    t = FakeTransport()
    t.get_result = {
        "00080018": {"vr": "UI", "Value": ["2.25.9"]},
        "00741000": {"vr": "CS", "Value": ["SCHEDULED"]},
    }
    UPSClient(t).update("2.25.9", {"00741204": {"vr": "SH", "Value": ["retuned"]}})
    method, path, params = t.calls[1]
    assert method == "POST"
    assert params is None
    assert "00081195" not in t.last_json


def test_change_state_claim_installs_a_new_transaction_uid():
    t = FakeTransport()
    t.get_result = {
        "00080018": {"vr": "UI", "Value": ["2.25.9"]},
        "00741000": {"vr": "CS", "Value": ["SCHEDULED"]},
    }
    UPSClient(t).change_state("2.25.9", "IN PROGRESS")
    assert t.calls[1][0:2] == ("put", "/workitems/2.25.9/state")
    body = t.last_json
    assert body["00741000"]["Value"] == ["IN PROGRESS"]
    assert body["00081195"]["Value"][0].startswith("2.25.")


def test_change_state_reuses_the_generated_transaction_uid():
    t = FakeTransport()
    # The claim starts from a SCHEDULED workitem with no lock.
    t.get_result = {
        "00080018": {"vr": "UI", "Value": ["2.25.9"]},
        "00741000": {"vr": "CS", "Value": ["SCHEDULED"]},
    }
    cl = UPSClient(t)
    cl.change_state("2.25.9", "IN PROGRESS")
    claim_uid = t.last_json["00081195"]["Value"][0]
    # GET never returns the Transaction UID (11.5.2), so the later CANCEL must
    # reuse the UID the claim generated and retained - not re-read it.
    t.get_result = {
        "00080018": {"vr": "UI", "Value": ["2.25.9"]},
        "00741000": {"vr": "CS", "Value": ["IN PROGRESS"]},
    }
    cl.change_state("2.25.9", "CANCELED", reason="user")
    body = t.last_json
    assert body["00081195"]["Value"] == [claim_uid]
    assert body["00741238"]["Value"] == ["user"]


def test_download_outputs_reads_the_nested_output_sequence(tmp_path):
    t = FakeTransport()
    t.get_result = {
        "00080018": {"vr": "UI", "Value": ["2.25.9"]},
        "0020000D": {"vr": "UI", "Value": ["1.2.3"]},
        "00741000": {"vr": "CS", "Value": ["COMPLETED"]},
        "00741216": {"vr": "SQ", "Value": [{
            "00404033": {"vr": "SQ", "Value": [{
                "00081150": {"vr": "UI", "Value": ["1.2.840.10008.5.1.4.1.1.7"]},
                "0020000E": {"vr": "UI", "Value": ["2.25.44"]},
                "00081155": {"vr": "UI", "Value": ["2.25.55"]},
            }]},
        }]},
    }
    t.post_result = FakeResponse()
    t.post_result.content = b"\x00\x01\x02"
    paths = UPSClient(t).download_outputs("2.25.9", out_dir=tmp_path)
    assert len(paths) == 1
    assert paths[0].read_bytes() == b"\x00\x01\x02"
    # The item omits the study UID; the URL falls back to the workitem's own.
    assert ("GET", "/studies/1.2.3/series/2.25.44/instances/2.25.55", None) in t.calls
    # The instance must be retrieved as binary DICOM, not DICOM JSON metadata.
    assert t.last_accept == 'multipart/related; type="application/dicom"'


def test_download_outputs_extracts_the_dicom_part_from_multipart(tmp_path):
    t = FakeTransport()
    t.get_result = {
        "00080018": {"vr": "UI", "Value": ["2.25.9"]},
        "0020000D": {"vr": "UI", "Value": ["1.2.3"]},
        "00741216": {"vr": "SQ", "Value": [{
            "00404033": {"vr": "SQ", "Value": [{
                "0020000E": {"vr": "UI", "Value": ["2.25.44"]},
                "00081155": {"vr": "UI", "Value": ["2.25.55"]},
            }]},
        }]},
    }
    boundary = "clarus-boundary-1-0"
    dicom = b"\x00" * 128 + b"DICM" + b"\x01\x02\x03"
    t.post_result = FakeResponse(headers={
        "Content-Type": f'multipart/related; type="application/dicom"; boundary="{boundary}"',
    })
    t.post_result.content = (
        f"--{boundary}\r\n"
        "Content-Type: application/dicom; transfer-syntax=1.2.840.10008.1.2.1\r\n\r\n"
    ).encode() + dicom + f"\r\n--{boundary}--\r\n".encode()
    paths = UPSClient(t).download_outputs("2.25.9", out_dir=tmp_path)
    assert len(paths) == 1
    assert paths[0].read_bytes() == dicom


def test_download_outputs_handles_nested_referenced_sop_sequence(tmp_path):
    t = FakeTransport()
    t.get_result = {
        "00080018": {"vr": "UI", "Value": ["2.25.9"]},
        "0020000D": {"vr": "UI", "Value": ["1.2.3"]},
        "00741216": {"vr": "SQ", "Value": [{
            "00404033": {"vr": "SQ", "Value": [{
                "0020000E": {"vr": "UI", "Value": ["2.25.44"]},
                "00081199": {"vr": "SQ", "Value": [
                    {"00081155": {"vr": "UI", "Value": ["2.25.55"]}},
                    {"00081155": {"vr": "UI", "Value": ["2.25.66"]}},
                ]},
            }]},
        }]},
    }
    t.post_result = FakeResponse()
    t.post_result.content = b"x"
    paths = UPSClient(t).download_outputs("2.25.9", out_dir=tmp_path)
    assert [p.name for p in paths] == ["2.25.55.dcm", "2.25.66.dcm"]
