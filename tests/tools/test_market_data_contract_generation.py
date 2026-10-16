"""Dynamic chart records retain bounded, typed Zod validation."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "market_data_stream_contract", Path(__file__).resolve().parents[2] / "scripts/market_data_stream_contract.py"
)
assert SPEC is not None and SPEC.loader is not None
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def test_bounded_record_of_strict_tagged_parameter_objects():
    schema = {
        "type": "object",
        "propertyNames": {"minLength": 1, "maxLength": 256},
        "maxProperties": 16,
        "additionalProperties": {
            "anyOf": [
                {
                    "type": "object",
                    "required": ["type", "value"],
                    "additionalProperties": False,
                    "properties": {"type": {"const": "INTEGER"}, "value": {"type": "integer", "minimum": 1}},
                },
                {
                    "type": "object",
                    "required": ["type", "value"],
                    "additionalProperties": False,
                    "properties": {"type": {"const": "BOOLEAN"}, "value": {"type": "boolean"}},
                },
            ]
        },
    }
    generated = GENERATOR._expression(schema)
    assert generated.startswith("z.record(z.string().min(1).max(256), z.union([z.strictObject(")
    assert 'z.literal("INTEGER")' in generated and 'z.literal("BOOLEAN")' in generated
    assert "Object.keys(value).length <= 16" in generated
    assert "passthrough" not in generated


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "additionalProperties": True},
        {"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": {"type": "string"}},
    ],
)
def test_open_or_mixed_objects_fail_closed(schema):
    with pytest.raises(ValueError):
        GENERATOR._expression(schema)


def test_unique_output_names_remain_unique_in_generated_validator():
    generated = GENERATOR._expression({"type": "array", "items": {"type": "string"}, "uniqueItems": True})
    assert generated == "z.array(z.string()).refine(value => new Set(value).size === value.length)"
    with pytest.raises(ValueError):
        GENERATOR._expression({"type": "array", "items": {"type": "object", "properties": {}}, "uniqueItems": True})


@pytest.mark.parametrize(
    "names",
    [
        {"type": "integer"},
        {"anyOf": [{"minLength": 1}, {"maxLength": 256}]},
        {"not": {"pattern": "^internal"}},
        {"minLength": 1, "unevaluatedProperties": False},
    ],
)
def test_unsupported_nested_record_key_constraints_fail_closed(names):
    with pytest.raises(ValueError):
        GENERATOR._expression({"type": "object", "propertyNames": names, "additionalProperties": {"type": "string"}})


def test_record_key_constraints_are_kept_when_pydantic_omits_string_type():
    generated = GENERATOR._expression(
        {
            "type": "object",
            "propertyNames": {"minLength": 1, "maxLength": 256, "pattern": "^[a-z]+$"},
            "additionalProperties": {"type": "string"},
        }
    )
    assert generated == 'z.record(z.string().min(1).max(256).regex(new RegExp("^[a-z]+$")), z.string())'
