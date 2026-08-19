from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.calculation import OnlyCalculationDataType
from onlyalpha.research import (
    OnlyResearchAnd,
    OnlyResearchComparison,
    OnlyResearchComparisonOperator,
    OnlyResearchDatasetFieldRef,
    OnlyResearchDefinition,
    OnlyResearchTypedLiteral,
    only_research_expression_fingerprint,
)
from tests.research.calculation.support import snapshot
from tests.research.definition.support import definition


def test_definition_identity_is_semantic_canonical_and_display_neutral() -> None:
    dataset = snapshot()[0].definition
    first = definition(dataset, metadata="alpha")
    second = definition(dataset, reverse_sweeps=True, metadata="beta")
    assert first.definition_fingerprint == second.definition_fingerprint
    assert first.to_dict()["display_metadata"] != second.to_dict()["display_metadata"]
    assert OnlyResearchDefinition.from_dict(first.to_dict()).definition_fingerprint == first.definition_fingerprint


def test_definition_strictly_rejects_unknown_field_and_version() -> None:
    payload = dict(definition(snapshot()[0].definition).to_dict())
    payload["unknown"] = True
    with pytest.raises(ValueError, match="unknown"):
        OnlyResearchDefinition.from_dict(payload)
    payload = deepcopy(dict(definition(snapshot()[0].definition).to_dict()))
    payload["schema_version"] = 2
    with pytest.raises(ValueError, match="unsupported Research Definition schema version"):
        OnlyResearchDefinition.from_dict(payload)


def test_sweep_duplicate_and_singleton_fail_closed() -> None:
    from onlyalpha.research import OnlyResearchSweepParameter

    with pytest.raises(ValueError, match="at least two"):
        OnlyResearchSweepParameter((1,))
    with pytest.raises(ValueError, match="duplicate"):
        OnlyResearchSweepParameter((1, 1))


def test_primary_output_is_serialized_but_not_semantic_identity() -> None:
    base = definition(snapshot()[0].definition)
    rsi = next(item for item in base.calculations if item.instance_key == "rsi")
    first = replace(rsi, published_outputs=("value", "zone"), primary_output="value")
    second = replace(rsi, published_outputs=("zone", "value"), primary_output="zone")
    left = replace(base, calculations=tuple(first if item is rsi else item for item in base.calculations))
    right = replace(base, calculations=tuple(second if item is rsi else item for item in base.calculations))
    assert left.definition_fingerprint == right.definition_fingerprint
    assert left.to_dict() != right.to_dict()


def test_boolean_and_is_associative_and_commutative_in_identity() -> None:
    literal = OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("1"))
    comparisons = tuple(
        OnlyResearchComparison(OnlyResearchComparisonOperator.GT, OnlyResearchDatasetFieldRef(name), literal)
        for name in ("open", "high", "close")
    )
    first = OnlyResearchAnd((comparisons[0], OnlyResearchAnd((comparisons[1], comparisons[2]))))
    second = OnlyResearchAnd((comparisons[2], comparisons[0], comparisons[1]))
    assert only_research_expression_fingerprint(first) == only_research_expression_fingerprint(second)
