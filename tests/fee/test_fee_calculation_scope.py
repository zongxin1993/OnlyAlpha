from datetime import date
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyCurrencyType, OnlyRuntimeMode
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee import (
    OnlyBrokerFeeReportingMode,
    OnlyFeeAuthority,
    OnlyFeeCalculationRequest,
    OnlyFeeCalculationScope,
    OnlyFeeConfigurationMode,
    OnlyFeeEngine,
    OnlyFeeRateRule,
    OnlyFeeStatus,
    OnlyFeeType,
    OnlyMarketFeeSchedule,
)

CNY = OnlyCurrency("CNY", 2, OnlyCurrencyType.FIAT)


def _schedule(scope: OnlyFeeCalculationScope, *, maximum: str | None = None) -> OnlyMarketFeeSchedule:
    return OnlyMarketFeeSchedule(
        "scope-test",
        "1",
        date(2026, 1, 1),
        None,
        CNY,
        "test",
        (
            OnlyFeeRateRule(
                OnlyFeeType.BROKER_COMMISSION,
                OnlyFeeAuthority.BROKER,
                percent_rate=Decimal("0.001"),
                minimum=Decimal("5"),
                maximum=None if maximum is None else Decimal(maximum),
                calculation_scope=scope,
            ),
        ),
        "GENERIC",
    )


def test_fill_and_order_cumulative_scopes_use_explicit_inputs_and_caps() -> None:
    fill = _schedule(OnlyFeeCalculationScope.FILL).calculate(
        notional=Decimal("100"),
        quantity=Decimal("1"),
        side="BUY",
        offset="OPEN",
        liquidity_role=None,
        status=OnlyFeeStatus.CONFIRMED,
    )[0]
    assert fill.amount.amount == Decimal("5.00")
    assert fill.calculation_scope is OnlyFeeCalculationScope.FILL

    cumulative = _schedule(OnlyFeeCalculationScope.ORDER_CUMULATIVE, maximum="8")
    first = cumulative.calculate(
        notional=Decimal("100"),
        quantity=Decimal("1"),
        cumulative_notional=Decimal("100"),
        cumulative_quantity=Decimal("1"),
        side="BUY",
        offset="OPEN",
        liquidity_role=None,
        status=OnlyFeeStatus.CONFIRMED,
    )[0]
    capped = cumulative.calculate(
        notional=Decimal("100"),
        quantity=Decimal("1"),
        cumulative_notional=Decimal("10000"),
        cumulative_quantity=Decimal("2"),
        side="BUY",
        offset="OPEN",
        liquidity_role=None,
        status=OnlyFeeStatus.CONFIRMED,
    )[0]
    assert first.amount.amount == Decimal("5.00")
    assert first.metadata["raw_amount"] == "0.10"
    assert capped.amount.amount == Decimal("8.00")
    with pytest.raises(ValueError, match="cumulative Order authority"):
        cumulative.calculate(
            notional=Decimal("100"),
            quantity=Decimal("1"),
            side="BUY",
            offset="OPEN",
            liquidity_role=None,
            status=OnlyFeeStatus.CONFIRMED,
        )


def test_cumulative_broker_report_fails_closed_instead_of_becoming_fill_fee() -> None:
    request = OnlyFeeCalculationRequest(
        "runtime",
        "cluster",
        "account",
        "order",
        "trade",
        "instrument",
        "profile",
        "1",
        date(2026, 1, 1),
        "BUY",
        "OPEN",
        None,
        Decimal("10"),
        Decimal("1"),
        OnlyMoney(Decimal("10"), CNY),
        Decimal("1"),
        CNY,
        "broker",
        OnlyBrokerFeeReportingMode.ORDER_CUMULATIVE,
        OnlyMoney(Decimal("5"), CNY),
    )
    with pytest.raises(ValueError, match="BROKER_CUMULATIVE_FEE_REPORT_UNSUPPORTED"):
        OnlyFeeEngine().resolve_trade_fee(
            request,
            runtime_mode=OnlyRuntimeMode.LIVE,
            market_schedule=None,
            broker_schedule=None,
            market_mode=OnlyFeeConfigurationMode.NONE,
            broker_mode=OnlyFeeConfigurationMode.REPORTED,
        )
