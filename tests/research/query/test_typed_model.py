from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.research.query import (
    OnlyResearchQueryError,
    OnlyResearchTypedScalar,
    OnlyResearchTypedScalarStatus,
    OnlyResearchTypedScalarValueKind,
    OnlyResearchTypedStatisticSeriesQuery,
)


@pytest.mark.parametrize(
    "status",
    (
        OnlyResearchTypedScalarStatus.NO_VALID_OBSERVATIONS,
        OnlyResearchTypedScalarStatus.INSUFFICIENT_OBSERVATIONS,
        OnlyResearchTypedScalarStatus.ZERO_VARIANCE,
        OnlyResearchTypedScalarStatus.NOT_APPLICABLE,
    ),
)
def test_non_valid_typed_scalars_preserve_status_and_forbid_numeric_defaults(
    status: OnlyResearchTypedScalarStatus,
) -> None:
    scalar = OnlyResearchTypedScalar(
        "research.test.metric@1",
        OnlyResearchTypedScalarValueKind.DECIMAL,
        status,
    )
    assert scalar.status is status
    assert scalar.integer_value is None
    assert scalar.decimal_value is None
    with pytest.raises(ValueError, match="must not carry"):
        replace(scalar, decimal_value=Decimal("0"))


def test_typed_scalars_keep_exact_decimal_and_integer_types() -> None:
    exact_decimal = Decimal("0.123456789012")
    decimal_scalar = OnlyResearchTypedScalar(
        "research.test.decimal@1",
        OnlyResearchTypedScalarValueKind.DECIMAL,
        OnlyResearchTypedScalarStatus.VALID,
        decimal_value=exact_decimal,
    )
    integer_scalar = OnlyResearchTypedScalar(
        "research.test.integer@1",
        OnlyResearchTypedScalarValueKind.INTEGER,
        OnlyResearchTypedScalarStatus.VALID,
        integer_value=9007199254740993,
    )
    assert type(decimal_scalar.decimal_value) is Decimal
    assert decimal_scalar.decimal_value == exact_decimal
    assert type(integer_scalar.integer_value) is int
    assert integer_scalar.integer_value == 9007199254740993


def test_typed_series_query_reuses_exact_range_cursor_and_limit_validation() -> None:
    identity = "a" * 64
    statistics = "b" * 64
    with pytest.raises(OnlyResearchQueryError):
        OnlyResearchTypedStatisticSeriesQuery(identity, statistics, from_ts_event_ns=2, to_ts_event_ns=2)
    with pytest.raises(OnlyResearchQueryError):
        OnlyResearchTypedStatisticSeriesQuery(identity, statistics, limit=0)
    with pytest.raises(OnlyResearchQueryError):
        OnlyResearchTypedStatisticSeriesQuery(identity, statistics, after_ts_event_ns=True)
