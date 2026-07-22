from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from onlyalpha.broker import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.enums import (
    OnlyCurrencyType,
    OnlyLiquiditySide,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
)
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.execution import OnlyCommittedExecutionFact, OnlyCommittedExecutionJournal
from onlyalpha.fee import OnlyBrokerFeeReportingMode, OnlyFeeBreakdown, OnlyFeeStatus
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.strategy.identifiers import OnlyStrategyId


def _fact(*, runtime: str = "runtime", gateway: str = "gateway") -> OnlyCommittedExecutionFact:
    timestamp = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))
    currency = OnlyCurrency("CNY", 2, OnlyCurrencyType.FIAT)
    zero = OnlyMoney(Decimal("0.00"), currency)
    fee = OnlyFeeBreakdown.empty(currency, OnlyFeeStatus.CONFIRMED)
    return OnlyCommittedExecutionFact(
        execution_id=f"EXEC-{runtime}-{gateway}-trade",
        execution_sequence=1,
        trade_id=OnlyTradeId("trade"),
        venue_trade_id="venue-trade",
        order_id=OnlyOrderId("order"),
        client_order_id="client-order",
        request_id="request",
        broker_update_id=OnlyBrokerUpdateId("update"),
        runtime_id=OnlyRuntimeId(runtime),
        gateway_id=OnlyBrokerGatewayId(gateway),
        account_id=OnlyAccountId("account"),
        cluster_id=OnlyClusterId("cluster"),
        strategy_id=OnlyStrategyId("strategy"),
        instrument_id=OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG")),
        venue_id="XSHG",
        source_sequence=7,
        processing_sequence=3,
        correlation_id="correlation",
        causation_id="causation",
        external_event_id="external",
        ts_event=timestamp,
        ts_init=timestamp,
        ts_committed=timestamp,
        trading_day=OnlyTradingDay(date(2026, 1, 1)),
        order_side=OnlyOrderSide.BUY,
        order_type=OnlyOrderType.LIMIT,
        offset=OnlyOffset.OPEN,
        position_side=OnlyPositionSide.LONG,
        position_effect=OnlyPositionEffect.OPEN,
        position_mode=OnlyPositionMode.NETTING,
        liquidity_side=OnlyLiquiditySide.TAKER,
        fill_quantity=OnlyQuantity(Decimal("2"), 0),
        fill_price=OnlyPrice(Decimal("10.00"), 2),
        cumulative_filled_quantity=OnlyQuantity(Decimal("2"), 0),
        remaining_quantity=OnlyQuantity(Decimal("0"), 0),
        order_status_after=OnlyOrderStatus.FILLED,
        currency=currency,
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        gross_notional=OnlyMoney(Decimal("20.00"), currency),
        settled_notional=OnlyMoney(Decimal("20.00"), currency),
        authoritative_fee_total=zero,
        market_fee=zero,
        broker_fee=zero,
        tax=zero,
        commission=zero,
        other_fee=zero,
        reported_broker_fee=None,
        fee_reporting_mode=OnlyBrokerFeeReportingMode.NONE,
        reference_price=OnlyPrice(Decimal("10.00"), 2),
        slippage=zero,
        realized_pnl_delta=zero,
        cash_delta=OnlyMoney(Decimal("-20.00"), currency),
        fee_instruction_id="fee-instruction",
        fee_authority="NONE",
        fee_status=OnlyFeeStatus.CONFIRMED.value,
        market_fee_schedule_ids=(),
        market_fee_schedule_versions=(),
        broker_fee_schedule_ids=(),
        broker_fee_schedule_versions=(),
        fee_breakdown=fee,
        market_profile_id="GENERIC_T0_CASH",
        market_profile_version="1",
        compiled_rule_fingerprint="compiled",
        reference_fingerprint="reference",
        trade_instruction_id="trade-instruction",
        settlement_instruction_id="settlement",
        settlement_status="SETTLED",
        asset_available_on=OnlyTradingDay(date(2026, 1, 1)),
        cash_available_on=OnlyTradingDay(date(2026, 1, 1)),
        legal_settlement_date=OnlyTradingDay(date(2026, 1, 1)),
        margin_instruction_id=None,
        margin_action=None,
        margin_currency=None,
        margin_amount=None,
        reserved_margin_delta=None,
        occupied_margin_delta=None,
        released_margin_delta=None,
        maintenance_margin_after=None,
        position_quantity_delta=Decimal("2"),
        position_realized_pnl_delta=zero,
        allocation_quantity_delta=Decimal("2"),
        account_cash_delta=OnlyMoney(Decimal("-20.00"), currency),
        account_fee_delta=zero,
        account_realized_pnl_delta=zero,
        ledger_cash_delta=OnlyMoney(Decimal("-20.00"), currency),
        ledger_fee_delta=zero,
        ledger_realized_pnl_delta=zero,
    )


def test_committed_execution_journal_is_ordered_serializable_immutable_and_stably_hashed() -> None:
    fact = _fact()
    journal = OnlyCommittedExecutionJournal(fact.runtime_id, (fact.gateway_id,))

    assert journal.append(fact)
    assert journal.records() == (fact,)
    assert OnlyCommittedExecutionFact.from_json(fact.to_json()) == fact
    assert OnlyCommittedExecutionFact.from_json(fact.to_json()).stable_hash == fact.stable_hash
    with pytest.raises(FrozenInstanceError):
        fact.execution_id = "changed"  # type: ignore[misc]


def test_journal_rejects_duplicate_trade_and_duplicate_update_without_advancing_sequence() -> None:
    fact = _fact()
    journal = OnlyCommittedExecutionJournal(fact.runtime_id, (fact.gateway_id,))
    assert journal.append(fact)
    assert not journal.append(replace(fact, broker_update_id=OnlyBrokerUpdateId("update-2")))
    assert not journal.append(replace(fact, trade_id=OnlyTradeId("trade-2")))
    assert journal.next_execution_sequence == 2


def test_runtime_and_gateway_scopes_are_isolated() -> None:
    fact = _fact()
    left = OnlyCommittedExecutionJournal(OnlyRuntimeId("runtime"), (OnlyBrokerGatewayId("gateway"),))
    right = OnlyCommittedExecutionJournal(OnlyRuntimeId("other-runtime"), (OnlyBrokerGatewayId("other-gateway"),))
    assert left.append(fact)
    with pytest.raises(ValueError, match="another Runtime or Gateway"):
        right.append(fact)
    other = _fact(runtime="other-runtime", gateway="other-gateway")
    assert right.append(other)
    assert left.records() == (fact,)
    assert right.records() == (other,)
