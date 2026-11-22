"""CLI for the SlicerUPS core (works inside and outside 3D Slicer).

Verbs mirror the Weasis `ups:` commands and the dwv surface:

    python run_ups.py search --root http://host:8042/dicomweb --modality CT
    python run_ups.py run --root ... --study 1.2.3 --code 99CLARUS:CT-ORGAN-SEG
    python run_ups.py watch --root ... --uid <workitem-uid> [--watch-mode poll]
    python run_ups.py outputs --root ... --uid <workitem-uid> --out /tmp/results
    python run_ups.py cancel --root ... --uid <workitem-uid> --reason "..."
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Allow running the script directly from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slicer_ups_client import Catalog, Code, DicomwebClient, UPSClient  # noqa: E402

log = logging.getLogger("slicer_ups_client")


def _client(args: argparse.Namespace) -> UPSClient:
    return UPSClient(DicomwebClient(args.root, token=args.token))


def _print_workitem(item) -> None:
    print(json.dumps({"uid": item.uid, "state": item.state}, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_ups")
    parser.add_argument("--root", required=True, help="DICOMweb root, e.g. http://host:8042/dicomweb")
    parser.add_argument("--token", help="Bearer token (optional)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("search")
    p.add_argument("--modality")
    p.add_argument("--body-part", dest="body_part")

    p = sub.add_parser("run")
    p.add_argument("--study", required=True)
    p.add_argument("--code", required=True, help="value or scheme:value")
    p.add_argument("--modality", default="CT")
    p.add_argument("--body-part", dest="body_part", help="body part for catalog matching")
    p.add_argument("--catalog", help="path to a catalog JSON/YAML (alternative to --code)")
    p.add_argument("--watch-mode", dest="watch_mode", default="auto")
    p.add_argument("--poll-interval", dest="poll_interval", type=float, default=2.0)
    p.add_argument("--timeout", type=float)

    p = sub.add_parser("watch")
    p.add_argument("--uid", required=True)
    p.add_argument("--watch-mode", dest="watch_mode", default="auto")
    p.add_argument("--poll-interval", dest="poll_interval", type=float, default=2.0)
    p.add_argument("--timeout", type=float)

    p = sub.add_parser("cancel")
    p.add_argument("--uid", required=True)
    p.add_argument("--reason")

    p = sub.add_parser("outputs")
    p.add_argument("--uid", required=True)
    p.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    client = _client(args)

    if args.verb == "search":
        for item in client.search({"Modality": args.modality} if args.modality else {}):
            _print_workitem(item)
    elif args.verb == "run":
        code = _resolve_code(args)
        uid = client.run(
            args.study,
            code,
            modality=args.modality,
            watch_mode=args.watch_mode,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
        )
        print(uid)
    elif args.verb == "watch":
        item = client.watch(
            args.uid,
            mode=args.watch_mode,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
        )
        _print_workitem(item)
    elif args.verb == "cancel":
        client.cancel(args.uid, reason=args.reason)
    elif args.verb == "outputs":
        paths = client.download_outputs(args.uid, out_dir=args.out)
        for path in paths:
            print(path)
    return 0


def _resolve_code(args: argparse.Namespace) -> Code:
    if args.catalog:
        catalog = Catalog(Path(args.catalog))
        body_part = getattr(args, "body_part", None)
        code = catalog.match(args.modality, body_part)
        if code is None:
            qualifier = f" and body-part {body_part}" if body_part else ""
            raise SystemExit(f"no catalog entry matches modality {args.modality}{qualifier}")
        return code
    value, _, scheme = args.code.partition(":")
    return Code(value=value, scheme=scheme or "99CLARUS", meaning="")


if __name__ == "__main__":
    raise SystemExit(main())
