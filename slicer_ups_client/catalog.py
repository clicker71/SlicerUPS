"""Neutral procedure catalog: match a study to a UPS workitem code.

Until Supplement 251 / IHE AISCap ships, the catalog is a plain JSON (or
YAML when PyYAML is installed) file, not clinfer rules. Export from clinfer
is optional; for dcm4chee/Orthanc the catalog is described by hand.

Format:

    {
      "procedures": [
        {
          "match": {"modality": ["CT"], "body_part": "LUNG"},
          "code": {"value": "CT-ORGAN-SEG", "scheme": "99CLARUS", "meaning": "..."},
          "result": {"kind": "rtstruct"}
        }
      ]
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .models import Code


@dataclass
class Procedure:
    modality: list[str]
    body_part: Optional[str]
    code: Code


def _load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("YAML catalog needs PyYAML; use a .json catalog") from exc
        return yaml.safe_load(text)
    return json.loads(text)


class Catalog:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._procedures: list[Procedure] = []
        if path is not None:
            self.load(path)

    def load(self, path: Path) -> None:
        data = _load(path)
        self._procedures = [
            Procedure(
                modality=list(entry.get("match", {}).get("modality", [])),
                body_part=entry.get("match", {}).get("body_part"),
                code=Code(
                    value=entry["code"]["value"],
                    scheme=entry["code"].get("scheme", ""),
                    meaning=entry["code"].get("meaning", ""),
                ),
            )
            for entry in data.get("procedures", [])
        ]

    def match(self, modality: str, body_part: Optional[str] = None) -> Optional[Code]:
        """Return the first procedure whose modality/body-part match."""
        for proc in self._procedures:
            if modality in proc.modality or not proc.modality:
                if proc.body_part is None or proc.body_part == body_part:
                    return proc.code
        return None
