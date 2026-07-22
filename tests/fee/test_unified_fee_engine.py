from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee import (
    OnlyBrokerFeeReportingMode,
    OnlyBrokerFeeSchedule,
    OnlyFeeAuthority,
    OnlyFeeCalculationRequest,
    OnlyFeeConfigurationMode,
    OnlyFeeEngine,
    OnlyFeeRateRule,
    OnlyFeeStatus,
    OnlyFeeType,
    OnlyMarketFeeSchedule,
)

USD = OnlyCurrency("USD")


def _request(
    *, reporting_mode: OnlyBrokerFeeReportingMode = OnlyBrokerFeeReportingMode.NONE, reported: str | None = None
):
    return OnlyFeeCalculationRequest(
        "runtime",
        "cluster",
        "account",
        "order",
        "trade",
        "BTC.USD",
        "CRYPTO",
        "1",
        date(2026, 1, 2),
        "BUY",
        "OPEN",
        "TAKER",
        Decimal("100"),
        Decimal("2"),
        OnlyMoney(Decimal("200"), USD),
        Decimal(1),
        USD,
        "broker",
        reporting_mode,
        None if reported is None else OnlyMoney(Decimal(reported), USD),
    )


def _market() -> OnlyMarketFeeSchedule:
    return OnlyMarketFeeSchedule(
        "market",
        "1",
        date(2026, 1, 1),
        None,
        USD,
        "market",
        (OnlyFeeRateRule(OnlyFeeType.TAKER_FEE, OnlyFeeAuthority.VENUE, percent_rate=Decimal("0.01")),),
        "CRYPTO",
        "EX",
        "CRYPTO",
    )


def _broker() -> OnlyBrokerFeeSchedule:
    return OnlyBrokerFeeSchedule(
        "broker",
        "1",
        date(2026, 1, 1),
        None,
        USD,
        "broker",
        (OnlyFeeRateRule(OnlyFeeType.BROKER_COMMISSION, OnlyFeeAuthority.BROKER, percent_rate=Decimal("0.005")),),
        "broker",
    )


def test_backtest_combines_market_and_broker_once() -> None:
    fee = OnlyFeeEngine().resolve_trade_fee(
        _request(),
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        market_schedule=_market(),
        broker_schedule=_broker(),
        market_mode=OnlyFeeConfigurationMode.MODEL,
        broker_mode=OnlyFeeConfigurationMode.MODEL,
    )
    assert fee.status is OnlyFeeStatus.CONFIRMED
    assert fee.total == OnlyMoney(Decimal("3.00"), USD)


def test_live_all_in_report_never_stacks_market_fee() -> None:
    fee = OnlyFeeEngine().resolve_trade_fee(
        _request(reporting_mode=OnlyBrokerFeeReportingMode.ALL_IN, reported="4.00"),
        runtime_mode=OnlyRuntimeMode.LIVE,
        market_schedule=_market(),
        broker_schedule=_broker(),
        market_mode=OnlyFeeConfigurationMode.MODEL,
        broker_mode=OnlyFeeConfigurationMode.REPORTED,
    )
    assert fee.total == OnlyMoney(Decimal("4.00"), USD)
    assert len(fee.components) == 1


def test_instruction_is_deterministic_and_utc() -> None:
    engine = OnlyFeeEngine()
    request = _request()
    breakdown = engine.resolve_trade_fee(
        request,
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        market_schedule=_market(),
        broker_schedule=_broker(),
        market_mode=OnlyFeeConfigurationMode.MODEL,
        broker_mode=OnlyFeeConfigurationMode.MODEL,
    )
    instruction = engine.instruction(request, breakdown, datetime(2026, 1, 2, tzinfo=UTC), "model")
    assert instruction.idempotency_key == "fee:runtime:trade:CONFIRMED"
