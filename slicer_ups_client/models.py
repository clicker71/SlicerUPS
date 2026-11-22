"""Typed model and DICOM JSON constants for the UPS-RS client.

The core is UI-agnostic by contract: no `qt`, `slicer`, `Slicer`, `vtk`
imports anywhere under this package. All wire types are plain dataclasses
over the DICOM JSON model (PS3.18 Annex F): tags are 8 lowercase hex digits,
every element carries a `vr` and a `Value` list.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

# --- SOP Classes (PS3.6) ------------------------------------------------
UPS_PUSH_SOP_CLASS = "1.2.840.10008.5.1.4.34.6.1"
UPS_PULL_SOP_CLASS = "1.2.840.10008.5.1.4.34.6.2"
UPS_WATCH_SOP_CLASS = "1.2.840.10008.5.1.4.34.6.3"

# --- UPS-RS attributes (PS3.18 11 / PS3.6) ------------------------------
SOP_CLASS_UID = "00080016"
SOP_INSTANCE_UID = "00080018"
MODALITY = "00080060"
CODE_VALUE = "00080100"
CODING_SCHEME_DESIGNATOR = "00080102"
CODE_MEANING = "00080104"
REFERENCED_SERIES_SEQUENCE = "00081115"
REFERENCED_SOP_SEQUENCE = "00081199"
REFERENCED_SOP_CLASS_UID = "00081150"
REFERENCED_SOP_INSTANCE_UID = "00081155"
TRANSACTION_UID = "00081195"
AFFECTED_SOP_INSTANCE_UID = "00081000"
EVENT_TYPE_ID = "00001002"
PATIENT_ID = "00100020"
STUDY_INSTANCE_UID = "0020000D"
SERIES_INSTANCE_UID = "0020000E"
REQUESTED_PROCEDURE_ID = "00401001"
SCHEDULED_PROCEDURE_STEP_ID = "00400009"
SCHEDULED_WORKITEM_CODE_SEQUENCE = "00404018"
INPUT_INFORMATION_SEQUENCE = "00404021"
OUTPUT_INFORMATION_SEQUENCE = "00404033"
PROCEDURE_STEP_STATE = "00741000"
SCHEDULED_PROCEDURE_STEP_PRIORITY = "00741200"
PROCEDURE_STEP_LABEL = "00741204"
SCHEDULED_PROCESSING_PARAMETERS_SEQUENCE = "00741210"
REASON_FOR_CANCELLATION = "00741238"
SCHEDULED_PROCEDURE_STEP_START_DATETIME = "00404005"
INPUT_READINESS_STATE = "00404041"

# --- Content Item Macro (PS3.3 Table 10-2) ------------------------------
VALUE_TYPE = "0040a040"
CONCEPT_NAME_CODE_SEQUENCE = "0040a043"
NUMERIC_VALUE = "0040a30a"
TEXT_VALUE = "0040a160"
CONCEPT_CODE_SEQUENCE = "0040a168"

# --- UPS states (PS3.4 CC.2.1) ------------------------------------------
STATE_SCHEDULED = "SCHEDULED"
STATE_IN_PROGRESS = "IN PROGRESS"
STATE_COMPLETED = "COMPLETED"
STATE_CANCELED = "CANCELED"


def new_workitem_uid() -> str:
    """A UUID-derived SOP Instance UID: PS3.5 '2.25.' + the UUID as a decimal integer."""
    return f"2.25.{uuid.uuid4().int}"
TERMINAL_STATES = (STATE_COMPLETED, STATE_CANCELED)


@dataclass
class Code:
    """A coded value: Code Value / Coding Scheme Designator / Code Meaning."""

    value: str
    scheme: str
    meaning: str = ""

    def to_json(self) -> dict[str, dict]:
        return {
            CODE_VALUE: {"vr": "SH", "Value": [self.value]},
            CODING_SCHEME_DESIGNATOR: {"vr": "SH", "Value": [self.scheme]},
            CODE_MEANING: {"vr": "LO", "Value": [self.meaning]},
        }


@dataclass
class WorkitemParameter:
    """One Content Item of the Scheduled Processing Parameters Sequence.

    `value_type` is a PS3.3 Content Item Macro term (NUMERIC | TEXT | CODE |
    DATETIME | DATE | TIME | UIDREF | PNAME). `value` is a scalar matching the
    type: NUMERIC -> float/int, TEXT -> str, CODE -> Code.
    """

    concept_name: Code
    value_type: str
    value: Any


@dataclass
class Workitem:
    uid: str
    state: str
    raw: dict = field(default_factory=dict)
    parameters: list[WorkitemParameter] = field(default_factory=list)


@dataclass
class WorkitemEvent:
    """A typed N-EVENT-REPORT for a workitem state change."""

    workitem_uid: str
    state: str
    raw: dict = field(default_factory=dict)


def get_string(dataset: dict, tag: str) -> Optional[str]:
    """Read a single-valued string from a DICOM JSON element, or None."""
    el = dataset.get(tag)
    if not isinstance(el, dict):
        return None
    values = el.get("Value")
    if not values:
        return None
    first = values[0]
    if isinstance(first, dict):
        # object-valued VR (e.g. PN) -> best-effort Alphabetic
        return first.get("Alphabetic")
    return str(first)


def get_first_item(dataset: dict, tag: str) -> Optional[dict]:
    """Read the first item of a sequence, or None."""
    el = dataset.get(tag)
    if not isinstance(el, dict):
        return None
    values = el.get("Value")
    if not values or not isinstance(values[0], dict):
        return None
    return values[0]


def set_string(dataset: dict, tag: str, vr: str, value: str) -> dict:
    dataset[tag] = {"vr": vr, "Value": [value]}
    return dataset
