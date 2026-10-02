from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from itertools import product

import pyarrow as pa
import pytest
from onlyalpha_plugin_indicators.registration import TYPES, resolve_definition

from onlyalpha.calculation import OnlyCalculationDefinition
from onlyalpha.research.calculation import (
    OnlyResearchCalculationError,
    OnlyResearchCalculationPublicationContract,
    OnlyResearchOutputReadiness,
    OnlyResearchReadinessReason,
    OnlyResearchReadinessState,
    only_validate_research_output_readiness,
)
from onlyalpha.research.calculation.publication import RESEARCH_CALCULATION_PUBLICATION_CONTRACT_SCHEMA_VERSION
from onlyalpha.research.calculation.readiness import RESEARCH_CALCULATION_READINESS_CONTRACT_VERSION


def _definition(*, nullable: bool = True) -> OnlyCalculationDefinition:
    definition = resolve_definition(
        next(item for item in TYPES if item.type_id == "onlyalpha.indicator.sma"), {"period": 3}
    )
    return replace(definition, outputs=(replace(definition.outputs[0], nullable=nullable),))


def _readiness(states: list[str | None], reasons: list[str | None]) -> OnlyResearchOutputReadiness:
    return OnlyResearchOutputReadiness(pa.array(states, type=pa.string()), pa.array(reasons, type=pa.string()))


def test_publication_contract_v1_is_strict_and_round_trips() -> None:
    contract = OnlyResearchCalculationPublicationContract()
    assert contract.to_dict() == {
        "schema_version": 1,
        "calculation_result_schema_version": 2,
        "execution_evidence_schema_version": 2,
        "readiness_contract_version": 1,
    }
    assert OnlyResearchCalculationPublicationContract.from_dict(contract.to_dict()) == contract
    assert RESEARCH_CALCULATION_PUBLICATION_CONTRACT_SCHEMA_VERSION == 1
    assert RESEARCH_CALCULATION_READINESS_CONTRACT_VERSION == 1
    with pytest.raises(FrozenInstanceError):
        contract.schema_version = 2  # type: ignore[misc]


def test_publication_contract_rejects_bool_float_unknown_and_extra_fields() -> None:
    contract = OnlyResearchCalculationPublicationContract()
    for name, expected in contract.to_dict().items():
        for value in (True, False, float(expected), str(expected), None, 0, -1, expected + 1):
            payload: dict[str, object] = {**contract.to_dict(), name: value}
            with pytest.raises(ValueError):
                OnlyResearchCalculationPublicationContract.from_dict(payload)
            with pytest.raises(ValueError):
                replace(contract, **{name: value})
        payload = dict(contract.to_dict())
        del payload[name]
        with pytest.raises(ValueError):
            OnlyResearchCalculationPublicationContract.from_dict(payload)
    with pytest.raises(ValueError):
        OnlyResearchCalculationPublicationContract.from_dict({**contract.to_dict(), "extra": 1})
    with pytest.raises(ValueError):
        OnlyResearchCalculationPublicationContract.from_dict({})


def test_readiness_validation_preserves_zero_and_requires_exact_reason_pairing() -> None:
    values = pa.array([Decimal("0.000000000000"), Decimal("0.000000000000")], type=pa.decimal128(28, 12))
    readiness = _readiness(["PARTIAL", "READY"], ["WARMUP_INCOMPLETE", "NONE"])
    definition = _definition()
    fingerprint = definition.fingerprint
    for _ in range(2):
        only_validate_research_output_readiness(definition, {"value": values}, {"value": readiness}, row_count=2)
    assert values.to_pylist() == [Decimal("0.000000000000"), Decimal("0.000000000000")]
    assert readiness.states.to_pylist() == ["PARTIAL", "READY"]
    assert readiness.reasons.to_pylist() == ["WARMUP_INCOMPLETE", "NONE"]
    assert definition.fingerprint == fingerprint
    for state, reason in (("UNAVAILABLE", "INPUT_UNAVAILABLE"), ("PARTIAL", "NONE"), ("READY", "WARMUP_INCOMPLETE")):
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
            only_validate_research_output_readiness(
                definition, {"value": values.slice(0, 1)}, {"value": _readiness([state], [reason])}, row_count=1
            )


@pytest.mark.parametrize(
    ("state", "reason", "is_null", "nullable"),
    list(product(tuple(OnlyResearchReadinessState), tuple(OnlyResearchReadinessReason), (False, True), (False, True))),
)
def test_readiness_state_reason_value_truth_table(
    state: OnlyResearchReadinessState, reason: OnlyResearchReadinessReason, is_null: bool, nullable: bool
) -> None:
    valid = (
        state is OnlyResearchReadinessState.PARTIAL
        and reason is OnlyResearchReadinessReason.WARMUP_INCOMPLETE
        and (not is_null or nullable)
        or state is OnlyResearchReadinessState.READY
        and (
            (not is_null and reason is OnlyResearchReadinessReason.NONE)
            or (is_null and nullable and reason is OnlyResearchReadinessReason.VALUE_UNDEFINED)
        )
        or state is OnlyResearchReadinessState.UNAVAILABLE
        and is_null
        and reason
        in (OnlyResearchReadinessReason.INPUT_UNAVAILABLE, OnlyResearchReadinessReason.DEPENDENCY_UNAVAILABLE)
    )
    outputs = {"value": pa.array([None if is_null else Decimal("0")], type=pa.decimal128(28, 12))}
    readiness = {"value": _readiness([state.value], [reason.value])}
    if valid:
        only_validate_research_output_readiness(_definition(nullable=nullable), outputs, readiness, row_count=1)
    else:
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
            only_validate_research_output_readiness(_definition(nullable=nullable), outputs, readiness, row_count=1)


@pytest.mark.parametrize("target", ("outputs", "readiness"))
@pytest.mark.parametrize("mutation", ("missing", "extra", "wrong-output"))
def test_readiness_requires_exact_definition_output_membership(target: str, mutation: str) -> None:
    outputs = {"value": pa.array([Decimal("0")], type=pa.decimal128(28, 12))}
    readiness = {"value": _readiness(["READY"], ["NONE"])}
    changed = outputs if target == "outputs" else readiness
    if mutation == "missing":
        changed.clear()
    elif mutation == "extra":
        changed["other"] = changed["value"]
    else:
        changed["other"] = changed.pop("value")
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
        only_validate_research_output_readiness(_definition(), outputs, readiness, row_count=1)


@pytest.mark.parametrize("field", ("values", "states", "reasons"))
@pytest.mark.parametrize("length", (0, 2))
def test_readiness_rejects_row_count_mismatch(field: str, length: int) -> None:
    values = pa.array([Decimal("0")] * (length if field == "values" else 1), type=pa.decimal128(28, 12))
    readiness = _readiness(
        ["READY"] * (length if field == "states" else 1), ["NONE"] * (length if field == "reasons" else 1)
    )
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
        only_validate_research_output_readiness(_definition(), {"value": values}, {"value": readiness}, row_count=1)


@pytest.mark.parametrize("field", ("states", "reasons"))
@pytest.mark.parametrize("invalid", (None, "ready", " READY", "UNKNOWN", 1, True))
def test_readiness_rejects_null_non_string_and_noncanonical_enums(field: str, invalid: object) -> None:
    readiness = _readiness(["READY"], ["NONE"])
    readiness = replace(readiness, **{field: pa.array([invalid])})
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
        only_validate_research_output_readiness(
            _definition(),
            {"value": pa.array([Decimal("0")], type=pa.decimal128(28, 12))},
            {"value": readiness},
            row_count=1,
        )


@pytest.mark.parametrize("row_count", (True, False, 1.0, "1", -1, None))
def test_readiness_rejects_noncanonical_row_count(row_count: object) -> None:
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
        only_validate_research_output_readiness(
            _definition(),
            {"value": pa.array([Decimal("0")], type=pa.decimal128(28, 12))},
            {"value": _readiness(["READY"], ["NONE"])},
            row_count=row_count,  # type: ignore[arg-type]
        )


def test_readiness_accepts_chunked_and_empty_string_arrays() -> None:
    for count in (0, 1):
        values = pa.chunked_array([pa.array([Decimal("0")] * count, type=pa.decimal128(28, 12))])
        readiness = OnlyResearchOutputReadiness(
            pa.chunked_array([pa.array(["READY"] * count, type=pa.string())]),
            pa.chunked_array([pa.array(["NONE"] * count, type=pa.string())]),
        )
        only_validate_research_output_readiness(_definition(), {"value": values}, {"value": readiness}, row_count=count)


@pytest.mark.parametrize("field", ("states", "reasons"))
def test_readiness_rejects_non_arrow_and_wrong_string_family(field: str) -> None:
    for array in (["READY"], pa.array(["READY"], type=pa.large_string()), pa.array([b"READY"], type=pa.binary())):
        evidence = replace(_readiness(["READY"], ["NONE"]), **{field: array})
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
            only_validate_research_output_readiness(
                _definition(),
                {"value": pa.array([Decimal("0")], type=pa.decimal128(28, 12))},
                {"value": evidence},
                row_count=1,
            )


def test_readiness_rejects_missing_nested_carrier_and_non_arrow_values() -> None:
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
        only_validate_research_output_readiness(
            _definition(),
            {"value": pa.array([Decimal("0")], type=pa.decimal128(28, 12))},
            {"value": None},  # type: ignore[dict-item]
            row_count=1,
        )
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
        only_validate_research_output_readiness(
            _definition(),
            {"value": [Decimal("0")]},
            {"value": _readiness(["READY"], ["NONE"])},
            row_count=1,
        )


def test_readiness_validates_each_output_against_its_own_nullability() -> None:
    definition = _definition()
    definition = replace(
        definition,
        outputs=(definition.outputs[0], replace(definition.outputs[0], name="other", nullable=False)),
    )
    values = pa.array([None], type=pa.decimal128(28, 12))
    ready = _readiness(["READY"], ["VALUE_UNDEFINED"])
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
        only_validate_research_output_readiness(
            definition, {"value": values, "other": values}, {"value": ready, "other": ready}, row_count=1
        )
    only_validate_research_output_readiness(
        definition,
        {"value": values, "other": pa.array([Decimal("0")], type=pa.decimal128(28, 12))},
        {"value": ready, "other": _readiness(["READY"], ["NONE"])},
        row_count=1,
    )


def test_readiness_vocabulary_and_public_exports_are_exact() -> None:
    import onlyalpha.research as research
    import onlyalpha.research.calculation as calculation

    research_names = tuple(research.__all__)
    assert tuple(item.value for item in OnlyResearchReadinessState) == ("PARTIAL", "READY", "UNAVAILABLE")
    assert tuple(item.value for item in OnlyResearchReadinessReason) == (
        "NONE",
        "WARMUP_INCOMPLETE",
        "VALUE_UNDEFINED",
        "INPUT_UNAVAILABLE",
        "DEPENDENCY_UNAVAILABLE",
    )
    for name in (
        "OnlyResearchCalculationPublicationContract",
        "OnlyResearchOutputReadiness",
        "OnlyResearchReadinessState",
        "OnlyResearchReadinessReason",
        "only_validate_research_output_readiness",
    ):
        assert calculation.__all__.count(name) == 1
        assert research_names.count(name) == 1
        assert getattr(research, name) is getattr(calculation, name)
