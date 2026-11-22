"""Codec for the Scheduled Processing Parameters Sequence (0074,1210).

PS3.3 C.30.2 makes (0074,1210) Type 3 - a workitem may carry no parameters.
Each parameter is ONE Content Item (Content Item Macro, PS3.3 Table 10-2):

- Value Type (0040,A040): NUMERIC | TEXT | CODE | DATETIME | DATE | TIME |
  UIDREF | PNAME.
- Concept Name Code Sequence (0040,A043): the parameter name. Locally-defined
  names use the private 99 prefix (PS3.3 8.2), e.g. 99CLARUS:SENSITIVITY.
- Value: NUMERIC -> Numeric Value (0040,A30A) DS; TEXT -> Text Value
  (0040,A160) UT; CODE -> Concept Code Sequence (0040,A168).

Multi-value = one Content Item per value, all sharing the same Concept Name.
VR fidelity is preserved on both directions: object-valued fields stay SQ
objects and are never flattened.
"""
from __future__ import annotations

from typing import Any

from .models import (
    Code,
    WorkitemParameter,
    SCHEDULED_PROCESSING_PARAMETERS_SEQUENCE,
    VALUE_TYPE,
    CONCEPT_NAME_CODE_SEQUENCE,
    NUMERIC_VALUE,
    TEXT_VALUE,
    CONCEPT_CODE_SEQUENCE,
    get_string,
)


def encode_parameter(param: WorkitemParameter) -> dict:
    item: dict[str, dict] = {
        VALUE_TYPE: {"vr": "CS", "Value": [param.value_type]},
        CONCEPT_NAME_CODE_SEQUENCE: {"vr": "SQ", "Value": [param.concept_name.to_json()]},
    }
    if param.value_type == "CODE":
        code: Code = param.value
        item[CONCEPT_CODE_SEQUENCE] = {"vr": "SQ", "Value": [code.to_json()]}
    elif param.value_type == "TEXT":
        item[TEXT_VALUE] = {"vr": "UT", "Value": [str(param.value)]}
    elif param.value_type == "NUMERIC":
        item[NUMERIC_VALUE] = {"vr": "DS", "Value": [str(param.value)]}
    else:
        # DATETIME | DATE | TIME | UIDREF | PNAME: single string value, the
        # VR follows the type. Keep the same container as TEXT for now.
        item[TEXT_VALUE] = {"vr": "UT", "Value": [str(param.value)]}
    return item


def encode_parameters(params: list[WorkitemParameter]) -> dict | None:
    if not params:
        return None
    return {
        SCHEDULED_PROCESSING_PARAMETERS_SEQUENCE: {
            "vr": "SQ",
            "Value": [encode_parameter(p) for p in params],
        }
    }


def _decode_concept_name(item: dict) -> Code:
    seq = item.get(CONCEPT_NAME_CODE_SEQUENCE, {})
    values = seq.get("Value", []) if isinstance(seq, dict) else []
    first = values[0] if values and isinstance(values[0], dict) else {}
    return Code(
        value=get_string(first, "00080100") or "",
        scheme=get_string(first, "00080102") or "",
        meaning=get_string(first, "00080104") or "",
    )


def decode_parameter(item: dict) -> WorkitemParameter | None:
    value_type = get_string(item, VALUE_TYPE)
    if not value_type:
        return None
    concept_name = _decode_concept_name(item)
    if value_type == "CODE":
        seq = item.get(CONCEPT_CODE_SEQUENCE, {})
        values = seq.get("Value", []) if isinstance(seq, dict) else []
        first = values[0] if values and isinstance(values[0], dict) else {}
        value: Any = Code(
            value=get_string(first, "00080100") or "",
            scheme=get_string(first, "00080102") or "",
            meaning=get_string(first, "00080104") or "",
        )
    elif value_type == "NUMERIC":
        raw = get_string(item, NUMERIC_VALUE)
        value = float(raw) if raw is not None else None
    else:
        value = get_string(item, TEXT_VALUE)
    return WorkitemParameter(concept_name=concept_name, value_type=value_type, value=value)


def decode_parameters(workitem: dict) -> list[WorkitemParameter]:
    """Decode (0074,1210) from a raw DICOM JSON workitem into parameters."""
    seq = workitem.get(SCHEDULED_PROCESSING_PARAMETERS_SEQUENCE, {})
    values = seq.get("Value", []) if isinstance(seq, dict) else []
    params: list[WorkitemParameter] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        param = decode_parameter(item)
        if param is not None:
            params.append(param)
    return params
