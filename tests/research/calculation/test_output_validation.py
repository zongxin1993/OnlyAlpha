"""Shared structural validators do not issue execution provenance."""

from dataclasses import replace
from decimal import Decimal

import pyarrow as pa
import pytest
from onlyalpha_plugin_indicators.registration import TYPES, resolve_definition

from onlyalpha.research.calculation.errors import OnlyResearchCalculationError
from onlyalpha.research.calculation.output_validation import only_validate_research_outputs
from onlyalpha.research.calculation.readiness import (
    OnlyResearchOutputReadiness,
    only_validate_research_output_readiness,
)


@pytest.mark.parametrize(
    "outputs",
    (
        {},
        {"extra": pa.array([Decimal(1)], type=pa.decimal128(38, 12))},
        {"value": pa.array([1.0])},
        {"value": pa.array([True])},
        {"value": pa.array([], type=pa.decimal128(38, 12))},
    ),
)
def test_output_members_types_and_alignment_are_validated(outputs):
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_OUTPUT_INVALID"):
        only_validate_research_outputs(resolve_definition(TYPES[1], {"period": 1}), outputs, 1)


def test_registered_nonnullable_output_rejects_null():
    definition = resolve_definition(TYPES[1], {"period": 1})
    definition = replace(definition, outputs=(replace(definition.outputs[0], nullable=False),))
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_OUTPUT_INVALID"):
        only_validate_research_outputs(definition, {"value": pa.array([None], type=pa.decimal128(38, 12))}, 1)


@pytest.mark.parametrize(
    ("value", "state", "reason"),
    (
        (None, "READY", "NONE"),
        (Decimal(1), "PARTIAL", "NONE"),
        (Decimal(1), "READY", "WARMUP_INCOMPLETE"),
        (Decimal(1), "UNAVAILABLE", "INPUT_UNAVAILABLE"),
        (Decimal(1), "BAD", "NONE"),
        (Decimal(1), "READY", None),
    ),
)
def test_readiness_cannot_be_invented_from_null_or_invalid_state_reason(value, state, reason):
    definition = resolve_definition(TYPES[1], {"period": 1})
    outputs = {"value": pa.array([value], type=pa.decimal128(38, 12))}
    readiness = {
        "value": OnlyResearchOutputReadiness(pa.array([state], type=pa.string()), pa.array([reason], type=pa.string()))
    }
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
        only_validate_research_output_readiness(definition, outputs, readiness, row_count=1)
