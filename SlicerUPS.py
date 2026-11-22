"""SlicerUPS - ScriptedLoadableModule entry point.

This file is the Slicer-side bridge only. It MAY import slicer; the core
package (slicer_ups_client/) must never. It is CLI-first: `parent.hidden`
keeps the module out of the GUI module list until a GUI panel lands, while
the core and the CLI remain fully usable.

`import_outputs(paths)` is the one MRML-facing boundary: the core downloads
DICOM to disk, this module loads it into the scene.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import slicer
from slicer.ScriptedLoadableModule import ScriptedLoadableModule

log = logging.getLogger("SlicerUPS")


class SlicerUPS(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "SlicerUPS"
        self.parent.categories = ["Informatics"]
        self.parent.dependencies = []
        self.parent.contributors = ["Daniil Solgalov (Clarus PACS)"]
        self.parent.acknowledgementText = (
            "UPS-RS (PS3.18) task requester/watcher. MIT."
        )
        self.parent.helpText = (
            "CLI-first client for DICOMweb UPS-RS. Use the slicer_ups_client "
            "package from Python or scripts/run_ups.py from the CLI."
        )
        # CLI-only for now: keep out of the GUI module list. Flip to False and
        # add a Widget when a GUI lands.
        self.parent.hidden = True


def import_outputs(paths: Iterable[str | Path]) -> list[str]:
    """Load result DICOM files into the MRML scene. Returns loaded node IDs."""
    loaded: list[str] = []
    for path in paths:
        file_path = str(path)
        nodes = slicer.util.loadVolume(file_path, returnNode=True)
        if nodes is not None:
            loaded.append(nodes.GetID())
    return loaded
