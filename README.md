# SlicerUPS

CLI-first client for DICOMweb UPS-RS (PS3.18 section 11), for 3D Slicer and
for the command line. One standard task contract - search / run / cancel /
watch / download_outputs - against any conformant origin.

- **[Clarus](https://github.com/clicker71/clarus-pacs)**: full WebSocket channel
  (push, instant notification).
- **dcm4chee-arc**: no WebSocket server; the client transparently falls back
  to polling.

The user does not think about the transport; the result arrives when it is
ready.

## Layering

- `slicer_ups_client/` - the core. Pure Python, **no Qt/Slicer imports**.
- `SlicerUPS.py` - the Slicer bridge: registers the module and imports results
  into the MRML scene (`import_outputs`).
- `hooks/` - examples for UI writers. Qt and shortcuts are allowed here.

The core only DOWNLOADS DICOM to a temp folder; it never touches the scene.

## CLI

Common flags:

- `--root` - DICOMweb root URL (e.g. `http://localhost:8024/dicomweb`).
- `--token` - optional Bearer token.
- `-v` / `--verbose` - debug logging.

### search - list workitems

```sh
python scripts/run_ups.py --root http://localhost:8024/dicomweb search --modality CT
```

Queries `GET /workitems` and prints each workitem's UID and state. Optional
`--modality` / `--body-part` filters. A `204 No Content` answer prints nothing
(an empty list, never an error).

### run - create a workitem and wait for it

```sh
python scripts/run_ups.py --root http://localhost:8024/dicomweb \
    run --study 1.2.3 --code 99CLARUS:CT-ORGAN-SEG --watch-mode auto
```

POSTs a workitem for the study, then watches it until COMPLETED or CANCELED
and prints the workitem UID. Flags:

- `--study` - Study Instance UID.
- `--code` - workitem code (`value` or `scheme:value`).
- `--modality` - default CT.
- `--catalog` - alternative to `--code`: pick the code from a catalog file.
- `--watch-mode` - `auto` (default) | `websocket` | `poll`.
- `--poll-interval` - seconds between polls.
- `--timeout` - seconds before giving up.

### watch - wait for an existing workitem

```sh
python scripts/run_ups.py --root http://localhost:8024/dicomweb \
    watch --uid 1.2.3.4 --watch-mode auto
```

Blocks until the workitem reaches a terminal state and prints its final UID
and state. `--watch-mode auto` tries the WebSocket subscription and falls back
to polling; `websocket` / `poll` force one transport.

### cancel - cancel a workitem

```sh
python scripts/run_ups.py --root http://localhost:8024/dicomweb \
    cancel --uid 1.2.3.4 --reason "no longer needed"
```

Transitions the workitem to CANCELED (`PUT /workitems/{uid}/state`) carrying
Reason For Cancellation (0074,1238). `--reason` is optional.

### outputs - download the result instances

```sh
python scripts/run_ups.py --root http://localhost:8024/dicomweb \
    outputs --uid 1.2.3.4 --out /tmp/results
```

Reads Output Information Sequence (0040,4033) from the completed workitem and
downloads each referenced instance over WADO-RS into `--out` (defaults to a
temp dir), printing the file paths.

## Python

```python
from slicer_ups_client import UPSClient, DicomwebClient, Code

client = UPSClient(DicomwebClient("http://localhost:8024/dicomweb"))
uid = client.run("1.2.3", Code("CT-ORGAN-SEG", "99CLARUS"))
for path in client.download_outputs(uid):
    print(path)
```

## Task parameters

Workitem parameters travel through the Scheduled Processing Parameters
Sequence (0074,1210). Pass them to `run` / `create`:

```python
from slicer_ups_client import WorkitemParameter, Code

params = [
    WorkitemParameter(Code("99CLARUS:SENSITIVITY", "99CLARUS"), "NUMERIC", 0.7),
    WorkitemParameter(Code("99CLARUS:MODE", "99CLARUS"), "TEXT", "fast"),
]
```

## License

MIT.
