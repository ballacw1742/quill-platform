from __future__ import annotations

from runtime.validator import validate_output

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["confidence", "verdict"],
    "properties": {
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "verdict": {"type": "string", "enum": ["approve", "reject"]},
    },
    "additionalProperties": False,
}


def test_valid_output():
    ok, errs = validate_output({"confidence": 0.9, "verdict": "approve"}, SCHEMA)
    assert ok
    assert errs == []


def test_missing_required():
    ok, errs = validate_output({"confidence": 0.9}, SCHEMA)
    assert not ok
    assert any("verdict" in e for e in errs)


def test_enum_violation():
    ok, errs = validate_output({"confidence": 0.5, "verdict": "maybe"}, SCHEMA)
    assert not ok
    assert any("verdict" in e for e in errs)


def test_out_of_range():
    ok, errs = validate_output({"confidence": 2.0, "verdict": "approve"}, SCHEMA)
    assert not ok


def test_additional_properties_blocked():
    ok, errs = validate_output(
        {"confidence": 0.9, "verdict": "approve", "extra": 1}, SCHEMA
    )
    assert not ok
