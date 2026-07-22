from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee import (
    OnlyBrokerFeeReportingMode,
    OnlyBrokerFeeSchedule,
    OnlyFeeAuthority,
    OnlyFeeCalculationRequest,
    OnlyFeeConfigurationMode,
    OnlyFeeDifferenceReason,
    OnlyFeeEngine,
    OnlyFeeRateRule,
    OnlyFeeReconciliationService,
    OnlyFeeReconciliationStatus,
    OnlyFeeStatus,
    OnlyFeeType,
    OnlyMarketFeeSchedule,
    OnlyMarketFeeScheduleRegistry,
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


def test_schedule_registry_rejects_overlap_and_unknown_version() -> None:
    registry = OnlyMarketFeeScheduleRegistry()
    registry.register(_market())
    with pytest.raises(ValueError, match="overlap"):
        registry.register(
            OnlyMarketFeeSchedule(
                "market",
                "2",
                date(2026, 1, 2),
                None,
                USD,
                "market-v2",
                (),
                "CRYPTO",
                "EX",
                "CRYPTO",
            )
        )
    with pytest.raises(ValueError, match="exactly one"):
        registry.resolve_version("market", "missing")


def test_reconciliation_is_idempotent_and_preserves_signed_adjustment() -> None:
    engine = OnlyFeeEngine()
    request = _request()
    breakdown = engine.resolve_trade_fee(
        request,
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        market_schedule=_market(),
        broker_schedule=None,
        market_mode=OnlyFeeConfigurationMode.MODEL,
        broker_mode=OnlyFeeConfigurationMode.NONE,
    )
    instruction = engine.instruction(request, breakdown, datetime(2026, 1, 2, tzinfo=UTC), "model")
    service = OnlyFeeReconciliationService()
    result = service.reconcile(
        instruction,
        reported_amount=OnlyMoney(Decimal("1.50"), USD),
        external_reference="statement-1",
        reason=OnlyFeeDifferenceReason.REFUND,
        created_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert result.status is OnlyFeeReconciliationStatus.ADJUSTMENT_REQUIRED
    assert result.adjustment is not None
    assert result.adjustment.adjustment_amount == OnlyMoney(Decimal("-0.50"), USD)
    duplicate = service.reconcile(
        instruction,
        reported_amount=OnlyMoney(Decimal("1.50"), USD),
        external_reference="statement-1",
        reason=OnlyFeeDifferenceReason.REFUND,
        created_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert duplicate.status is OnlyFeeReconciliationStatus.DUPLICATE_REPORT


def test_unknown_material_fee_difference_blocks_reconciliation() -> None:
    engine = OnlyFeeEngine()
    request = _request()
    breakdown = engine.resolve_trade_fee(
        request,
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        market_schedule=_market(),
        broker_schedule=None,
        market_mode=OnlyFeeConfigurationMode.MODEL,
        broker_mode=OnlyFeeConfigurationMode.NONE,
    )
    instruction = engine.instruction(request, breakdown, datetime(2026, 1, 2, tzinfo=UTC), "model")
    result = OnlyFeeReconciliationService().reconcile(
        instruction,
        reported_amount=OnlyMoney(Decimal("5.00"), USD),
        external_reference="statement-2",
        reason=OnlyFeeDifferenceReason.UNKNOWN,
        created_at=datetime(2026, 1, 3, tzinfo=UTC),
        materiality_threshold=OnlyMoney(Decimal("0.01"), USD),
    )
    assert result.status is OnlyFeeReconciliationStatus.TRADING_BLOCKED
    assert result.adjustment is None
