# SlicerUPS

CLI-first client for DICOMweb UPS-RS (PS3.18 section 11), for 3D Slicer and
for the command line. One standard task contract - search / run / cancel /
watch / download_outputs - against any conformant origin.

- **Clarus**: full WebSocket channel (push, instant notification).
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

```sh
python scripts/run_ups.py --root http://host:8042/dicomweb \
    search --modality CT
python scripts/run_ups.py --root http://host:8042/dicomweb \
    run --study 1.2.3 --code 99CLARUS:CT-ORGAN-SEG --watch-mode auto
python scripts/run_ups.py --root http://host:8042/dicomweb \
    outputs --uid <workitem-uid> --out /tmp/results
```

## Python

```python
from slicer_ups_client import UPSClient, DicomwebClient, Code

client = UPSClient(DicomwebClient("http://host:8042/dicomweb"))
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
