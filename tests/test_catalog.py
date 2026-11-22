"""Catalog matching and the CLI --catalog / --body-part resolution path."""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from slicer_ups_client import Catalog, Code

REPO = Path(__file__).resolve().parents[1]

PROCEDURES = [
    {
        "match": {"modality": ["CT"], "body_part": "LUNG"},
        "code": {"value": "CT-ORGAN-SEG", "scheme": "99CLARUS", "meaning": "Organ segmentation"},
    },
    {
        "match": {"modality": ["CT"]},
        "code": {"value": "CT-BRAIN", "scheme": "99CLARUS", "meaning": "Brain segmentation"},
    },
    {
        "match": {"modality": ["DX", "CR"]},
        "code": {"value": "CXR-AI", "scheme": "99CLARUS", "meaning": "Chest X-ray AI"},
    },
]


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"procedures": PROCEDURES}), encoding="utf-8")
    return Catalog(path)


def _load_run_ups():
    sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location("run_ups", REPO / "scripts" / "run_ups.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_match_by_modality_and_body_part(catalog: Catalog) -> None:
    assert catalog.match("CT", "LUNG") == Code("CT-ORGAN-SEG", "99CLARUS", "Organ segmentation")


def test_match_falls_back_to_body_part_less_entry(catalog: Catalog) -> None:
    assert catalog.match("CT", "HEAD") == Code("CT-BRAIN", "99CLARUS", "Brain segmentation")


def test_match_without_body_part_skips_body_part_keyed_entries(catalog: Catalog) -> None:
    # An entry that sets body_part only matches when a body part is given.
    assert catalog.match("CT") == Code("CT-BRAIN", "99CLARUS", "Brain segmentation")


def test_match_no_modality(catalog: Catalog) -> None:
    assert catalog.match("MR") is None


def test_resolve_code_with_catalog_and_body_part(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"procedures": PROCEDURES}), encoding="utf-8")
    run_ups = _load_run_ups()
    args = argparse.Namespace(catalog=str(path), modality="CT", body_part="LUNG", code=None)
    assert run_ups._resolve_code(args) == Code("CT-ORGAN-SEG", "99CLARUS", "Organ segmentation")


def test_resolve_code_with_catalog_no_body_part(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"procedures": PROCEDURES}), encoding="utf-8")
    run_ups = _load_run_ups()
    args = argparse.Namespace(catalog=str(path), modality="CT", body_part=None, code=None)
    assert run_ups._resolve_code(args) == Code("CT-BRAIN", "99CLARUS", "Brain segmentation")
