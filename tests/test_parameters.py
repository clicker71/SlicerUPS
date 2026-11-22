"""Round-trip tests for the (0074,1210) parameters codec."""

from slicer_ups_client import Code, WorkitemParameter, encode_parameters, decode_parameters
from slicer_ups_client.models import SCHEDULED_PROCESSING_PARAMETERS_SEQUENCE


def _param(value_type, value, concept="99CLARUS:KEY"):
    return WorkitemParameter(Code(concept, "99CLARUS"), value_type, value)


def test_roundtrip_text_numeric_code():
    params = [
        _param("TEXT", "fast"),
        _param("NUMERIC", 0.7),
        _param("CODE", Code("LUNG", "99CLARUS", "Lung")),
    ]
    encoded = encode_parameters(params)
    assert SCHEDULED_PROCESSING_PARAMETERS_SEQUENCE in encoded
    seq = encoded[SCHEDULED_PROCESSING_PARAMETERS_SEQUENCE]
    assert len(seq["Value"]) == 3
    decoded = decode_parameters({SCHEDULED_PROCESSING_PARAMETERS_SEQUENCE: seq})
    assert decoded[0].value_type == "TEXT" and decoded[0].value == "fast"
    assert decoded[1].value_type == "NUMERIC" and decoded[1].value == 0.7
    assert decoded[2].value_type == "CODE" and decoded[2].value.value == "LUNG"


def test_empty_parameters_encode_none():
    assert encode_parameters([]) is None


def test_concept_name_is_a_sequence_not_a_string():
    # The Concept Name Code Sequence (0040,A043) must stay a SQ object. A
    # flattened string would be caught here by a KeyError on Value.
    encoded = encode_parameters([_param("TEXT", "x")])
    item = encoded[SCHEDULED_PROCESSING_PARAMETERS_SEQUENCE]["Value"][0]
    concept = item["0040a043"]["Value"][0]
    assert concept["00080100"]["Value"] == ["99CLARUS:KEY"]
