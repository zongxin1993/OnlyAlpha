from dataclasses import replace
from decimal import Decimal

import pyarrow as pa
import pytest
from onlyalpha_plugin_indicators import research
from onlyalpha_plugin_indicators.registration import TYPES, registrations, resolve_definition

from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationKind, OnlyCalculationRegistry
from onlyalpha.research.calculation import (
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationPublicationContract,
    only_validate_research_output_readiness,
)


def _backend(period):
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        registry.register(registration)
    definition = resolve_definition(TYPES[1], {"period": period})
    return definition, OnlyResearchCalculationBackendResolver(registry).resolve_readiness(
        definition, OnlyResearchCalculationPublicationContract()
    ).provider


def test_sma_period_three_emits_exact_values_and_readiness_atomically(monkeypatch) -> None:
    definition, backend = _backend(3)
    inputs = {"value": pa.array([Decimal(x) for x in ("0", "2", "4", "8")], type=pa.decimal128(38, 12))}
    original = inputs["value"].to_pylist()
    legacy = backend.execute(definition, inputs)
    calls = []
    kernel = research._standard

    def counted(definition, values):
        calls.append(values)
        return kernel(definition, values)

    monkeypatch.setattr(research, "_standard", counted)
    result = backend.execute_with_readiness(definition, inputs)
    assert len(calls) == 1
    assert result.outputs["value"].type == pa.decimal128(38, 12)
    assert result.outputs["value"].to_pylist() == [
        Decimal(x) for x in ("0.000000000000", "1.000000000000", "2.000000000000", "4.666666666667")
    ]
    assert result.outputs["value"].equals(legacy["value"])
    assert result.readiness["value"].states.to_pylist() == ["PARTIAL", "PARTIAL", "READY", "READY"]
    assert result.readiness["value"].reasons.to_pylist() == ["WARMUP_INCOMPLETE", "WARMUP_INCOMPLETE", "NONE", "NONE"]
    only_validate_research_output_readiness(definition, result.outputs, result.readiness, row_count=4)
    assert inputs["value"].to_pylist() == original


@pytest.mark.parametrize("period", (1, 3))
def test_sma_period_one_is_ready_from_first_exact_zero(period) -> None:
    definition, backend = _backend(period)
    inputs = {"value": pa.chunked_array([[Decimal("0")] * 4], type=pa.decimal128(38, 12))}
    result = backend.execute_with_readiness(definition, inputs)
    assert result.outputs["value"].to_pylist() == [Decimal("0.000000000000")] * 4
    assert result.readiness["value"].states.type == pa.string()
    assert result.readiness["value"].reasons.type == pa.string()
    assert result.readiness["value"].states.to_pylist() == (
        ["READY"] * 4 if period == 1 else ["PARTIAL", "PARTIAL", "READY", "READY"]
    )
    assert result.readiness["value"].reasons.to_pylist() == (
        ["NONE"] * 4 if period == 1 else ["WARMUP_INCOMPLETE", "WARMUP_INCOMPLETE", "NONE", "NONE"]
    )
    repeated = backend.execute_with_readiness(definition, inputs)
    assert repeated.outputs["value"].equals(result.outputs["value"])
    assert repeated.readiness["value"].states.equals(result.readiness["value"].states)


def test_non_sma_registration_does_not_claim_readiness_v1() -> None:
    capable = []
    for registration in registrations():
        expected = (
            (1,)
            if registration.backend is OnlyCalculationBackendKind.RESEARCH
            and registration.type_definition.type_id == "onlyalpha.indicator.sma"
            and registration.type_definition.semantic_version == "1"
            else ()
        )
        assert registration.readiness_contract_versions == expected
        if expected:
            capable.append(registration)
    assert len(capable) == 1


@pytest.mark.parametrize("mutation", ("ema", "version", "kind"))
def test_readiness_backend_rejects_non_sma_exact_identity(mutation) -> None:
    definition, backend = _backend(3)
    if mutation == "ema":
        definition = resolve_definition(TYPES[0], {"period": 3})
    elif mutation == "version":
        definition = replace(definition, semantic_version="2")
    else:
        definition = replace(definition, kind=OnlyCalculationKind.TARGET)
    with pytest.raises(ValueError, match="sma@1"):
        backend.execute_with_readiness(definition, {})


def test_empty_sma_readiness_is_empty_not_an_invented_observation() -> None:
    definition, backend = _backend(3)
    result = backend.execute_with_readiness(definition, {"value": pa.array([], type=pa.decimal128(38, 12))})
    only_validate_research_output_readiness(definition, result.outputs, result.readiness, row_count=0)
    assert result.outputs["value"].to_pylist() == []
    assert result.readiness["value"].states.to_pylist() == []
