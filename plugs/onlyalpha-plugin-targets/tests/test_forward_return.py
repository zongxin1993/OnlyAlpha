from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pyarrow as pa  # type: ignore[import-untyped]
import pytest
from hypothesis import given
from hypothesis import strategies as st
from onlyalpha_plugin_targets.registration import (
    FORWARD_RETURN,
    OnlyOfficialTargetDefinitionResolver,
    registrations,
    resolve_forward_return,
)

from onlyalpha.calculation import (
    TARGET_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyFactorKind,
    only_calculation_execution_shape,
)


def _definition(entry: int = 0, exit_: int = 2, source: str = "bar.close"):
    return resolve_forward_return(
        {"entry_offset": entry, "exit_offset": exit_},
        OnlyCalculationReference(None, "entry_price", source),
        OnlyCalculationReference(None, "exit_price", "bar.close"),
    )


def _execute(values: list[Decimal], *, entry: int = 0, exit_: int = 2):
    definition = _definition(entry, exit_)
    backend = registrations()[0].provider
    return backend.execute(
        definition,
        {
            "entry_price": pa.array(values, type=pa.decimal128(38, 12)),
            "exit_price": pa.array(values, type=pa.decimal128(38, 12)),
        },
    )["target_value"].to_pylist()


def test_target_contract_is_research_only_time_series_and_not_factor() -> None:
    registration = registrations()[0]
    assert FORWARD_RETURN.kind is OnlyCalculationKind.TARGET
    assert FORWARD_RETURN.factor_kind is None
    assert FORWARD_RETURN.outputs[0].semantic_type == TARGET_VALUE_SEMANTIC_TYPE
    assert registration.backend is OnlyCalculationBackendKind.RESEARCH
    assert only_calculation_execution_shape(FORWARD_RETURN) is OnlyFactorKind.TIME_SERIES


def test_offsets_bindings_round_trip_and_identity_are_exact() -> None:
    target5 = _definition(0, 5)
    assert target5 == type(target5).from_dict(target5.to_dict())
    assert target5.fingerprint == _definition(0, 5).fingerprint
    assert target5.fingerprint != _definition(0, 20).fingerprint
    assert target5.fingerprint != _definition(1, 5, "bar.open").fingerprint
    with pytest.raises(ValueError, match="exit_offset"):
        _definition(2, 2)
    with pytest.raises(ValueError, match="below its minimum"):
        _definition(-1, 2)


def test_forward_return_exact_axis_tail_and_index_semantics() -> None:
    values = [Decimal(value) for value in ("1", "2", "4", "8", "16")]
    assert _execute(values, entry=0, exit_=2) == [Decimal("3.000000000000")] * 3 + [None, None]
    assert _execute([Decimal("7")] * 5, entry=1, exit_=3) == [Decimal("0E-12")] * 2 + [None] * 3


@given(
    st.lists(
        st.decimals(min_value="0.01", max_value="100000", places=4, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=25,
    ),
    st.decimals(min_value="0.01", max_value="100", places=4, allow_nan=False, allow_infinity=False),
)
def test_positive_price_scaling_does_not_change_simple_return(values: list[Decimal], scale: Decimal) -> None:
    assert _execute(values, exit_=1) == _execute([value * scale for value in values], exit_=1)


@pytest.mark.parametrize("bad", (Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")))
def test_invalid_price_fails_closed_without_nan_or_infinity(bad: Decimal) -> None:
    with pytest.raises((ValueError, pa.ArrowInvalid)):
        _execute([Decimal("1"), bad], exit_=1)


def test_backend_rejects_wrong_semantic_definition() -> None:
    backend = registrations()[0].provider
    with pytest.raises(ValueError, match="unsupported official Target"):
        backend.execute(replace(_definition(), semantic_version="2"), {})


def test_resolver_rejects_calculation_node_input() -> None:
    with pytest.raises(ValueError, match="external Dataset"):
        OnlyOfficialTargetDefinitionResolver(FORWARD_RETURN).resolve(
            {"exit_offset": 2},
            {
                "entry_price": OnlyCalculationReference("a" * 64, "value"),
                "exit_price": OnlyCalculationReference(None, "value", "bar.close"),
            },
        )


def test_backend_rejects_invalid_inputs_offsets_and_numeric_contract() -> None:
    backend = registrations()[0].provider
    decimal = pa.decimal128(38, 12)
    values = pa.array([Decimal(1), Decimal(2)], type=decimal)
    with pytest.raises(ValueError, match="input names"):
        backend.execute(_definition(), {"entry_price": values})
    with pytest.raises(ValueError, match="lengths differ"):
        backend.execute(
            _definition(),
            {"entry_price": values, "exit_price": pa.array([Decimal(1)], type=decimal)},
        )
    with pytest.raises(ValueError, match="Arrow Decimal"):
        backend.execute(
            _definition(),
            {"entry_price": pa.array([1, 2]), "exit_price": values},
        )
    with pytest.raises(ValueError, match="must be an integer"):
        backend.execute(
            replace(_definition(), parameters={"entry_offset": True, "exit_offset": 2}),
            {"entry_price": values, "exit_price": values},
        )
    with pytest.raises(ValueError, match="offsets are invalid"):
        backend.execute(
            replace(_definition(), parameters={"entry_offset": 2, "exit_offset": 1}),
            {"entry_price": values, "exit_price": values},
        )
    nullable = pa.array([Decimal(1), None, Decimal(3)], type=decimal)
    with pytest.raises(ValueError, match="contains null"):
        backend.execute(
            _definition(exit_=1),
            {"entry_price": nullable, "exit_price": nullable},
        )
    with pytest.raises(ValueError, match="output_quantum"):
        backend.execute(
            replace(_definition(entry=0, exit_=1), numeric=replace(_definition().numeric, output_quantum=None)),
            {"entry_price": values, "exit_price": values},
        )
