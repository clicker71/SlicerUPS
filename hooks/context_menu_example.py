# EXAMPLE - add a "Run UPS" item to the Subject Hierarchy context menu.
# This file may import qt/slicer and may print. It is an example, not the core.

import logging

import slicer

from slicer_ups_client import UPSClient, DicomwebClient

log = logging.getLogger("SlicerUPS.hook")


def on_run_ups() -> None:
    study_uid = _selected_study_uid()
    if study_uid is None:
        slicer.util.messageBox("Select a study in Subject Hierarchy first.")
        return
    root = slicer.util.settingsValue("SlicerUPS/rootUrl", "http://localhost:8042/dicomweb")
    client = UPSClient(DicomwebClient(root))
    # Replace with a real workitem code (or a catalog lookup).
    uid = client.run(study_uid, code=None) if False else None  # placeholder
    log.info("started workitem %s", uid)


def _selected_study_uid() -> str | None:
    sh = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    item = sh.GetItemByDataNode(sh.GetCurrentSubjectHierarchyNode())
    node = sh.GetItemDataNode(item) if item else None
    return node.GetAttribute("DICOM.StudyInstanceUID") if node is not None else None
