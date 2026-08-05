"""Independent, deterministic prepared execution transaction fixtures."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.account.enums import OnlyAccountReservationState, OnlyAccountStatus, OnlyAccountType
from onlyalpha.broker import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import (
    OnlyCurrencyType,
    OnlyLiquiditySide,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
    OnlyTimeInForce,
)
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyOrderRequestId,
    OnlyPositionId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.event.model import OnlyEvent, OnlyEventSource, OnlyEventType
from onlyalpha.execution import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountCashReservationExecutionState,
    OnlyAccountExecutionProjection,
    OnlyAccountExecutionState,
    OnlyAllocationExecutionProjection,
    OnlyAllocationExecutionReplayMetadata,
    OnlyAllocationExecutionState,
    OnlyCommittedExecutionFactDraft,
    OnlyExecutionTransactionEventFactory,
    OnlyFeeExecutionProjection,
    OnlyFeeExecutionState,
    OnlyFeeInstructionReplay,
    OnlyMarginExecutionProjection,
    OnlyMarginExecutionState,
    OnlyMarginReservationExecutionProjection,
    OnlyMarginReservationExecutionStage,
    OnlyMarginReservationExecutionState,
    OnlyMarginReservationExecutionStatus,
    OnlyOrderExecutionProjection,
    OnlyOrderExecutionState,
    OnlyOrderFeeAccrualExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionExecutionReplayMetadata,
    OnlyPositionExecutionState,
    OnlyPositionReservationExecutionProjection,
    OnlyPositionReservationExecutionState,
    OnlyPreparedRuntimeTransaction,
    OnlyRiskExecutionProjection,
    OnlyRiskExecutionState,
    OnlyRiskReservationExecutionProjection,
    OnlyRiskReservationExecutionState,
    OnlyRuntimePrecondition,
    OnlyRuntimeProjection,
    OnlyRuntimeProjectionComponent,
    OnlyRuntimeProjectionIdentity,
    OnlySettlementExecutionProjection,
    OnlySettlementExecutionState,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyCashReservationExecutionState,
    OnlyStrategyLedgerExecutionProjection,
    OnlyStrategyLedgerExecutionState,
    OnlyValuationExecutionProjection,
    OnlyValuationExecutionState,
    only_execution_state_hash,
    only_runtime_transaction_id,
    only_with_execution_projection_hash,
)
from onlyalpha.fee import (
    OnlyBrokerFeeReportingMode,
    OnlyFeeBreakdown,
    OnlyFeeStatus,
    OnlyOrderFeeAccrualExecutionState,
)
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import (
    OnlyPositionMode,
    OnlyPositionReservationStage,
    OnlyPositionReservationState,
    OnlyPositionSide,
    OnlyPositionStatus,
    OnlySettlementBucket,
)
from onlyalpha.position.identifiers import OnlyPositionAllocationId, OnlyPositionReservationId
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey
from onlyalpha.risk.enums import OnlyRiskLevel, OnlyRiskReservationState, OnlyRiskReservationType
from onlyalpha.risk.identifiers import OnlyRiskReservationId
from onlyalpha.strategy.identifiers import OnlyStrategyId
from onlyalpha.strategy_ledger.enums import (
    OnlyStrategyCashEntryType,
    OnlyStrategyCashReservationStage,
    OnlyStrategyCashReservationState,
    OnlyStrategyLedgerStatus,
)
from onlyalpha.strategy_ledger.identifiers import (
    OnlyStrategyCashEntryId,
    OnlyStrategyCashReservationId,
    OnlyStrategyLedgerId,
)
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.models import OnlyStrategyCashEntry
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind

_TEST_RUNTIME_ID = OnlyRuntimeId("runtime")
_TEST_TRADE_ID = OnlyTradeId("trade")
_TEST_UPDATE_ID = OnlyBrokerUpdateId("update")


def only_test_execution_fact_draft(
    *,
    runtime_id: OnlyRuntimeId = _TEST_RUNTIME_ID,
    trade_id: OnlyTradeId = _TEST_TRADE_ID,
    update_id: OnlyBrokerUpdateId = _TEST_UPDATE_ID,
    fill_index: int = 1,
) -> OnlyCommittedExecutionFactDraft:
    timestamp = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))
    currency = _currency()
    zero = _money("0.00")
    return OnlyCommittedExecutionFactDraft(
        execution_id=f"EXEC-{runtime_id}-{trade_id}",
        trade_id=trade_id,
        venue_trade_id="venue-trade",
        order_id=OnlyOrderId("order"),
        client_order_id="client-order",
        request_id="request",
        broker_update_id=update_id,
        runtime_id=runtime_id,
        gateway_id=OnlyBrokerGatewayId("gateway"),
        account_id=OnlyAccountId("account"),
        cluster_id=OnlyClusterId("cluster"),
        strategy_id=OnlyStrategyId("strategy"),
        instrument_id=_instrument(),
        venue_id="XSHG",
        source_sequence=7,
        processing_sequence=3,
        correlation_id="correlation",
        causation_id="causation",
        external_event_id="external",
        ts_event=timestamp,
        ts_init=timestamp,
        trading_day=_day(),
        order_side=OnlyOrderSide.BUY,
        order_type=OnlyOrderType.LIMIT,
        offset=OnlyOffset.OPEN,
        position_side=OnlyPositionSide.LONG,
        position_effect=OnlyPositionEffect.OPEN,
        position_mode=OnlyPositionMode.NETTING,
        liquidity_side=OnlyLiquiditySide.TAKER,
        fill_quantity=_quantity("2"),
        fill_price=_price("10.00"),
        cumulative_filled_quantity=_quantity("2"),
        remaining_quantity=_quantity("0"),
        order_status_after=OnlyOrderStatus.FILLED,
        fill_identity=f"EFILL-{hashlib.sha256(f'{runtime_id}|{trade_id}'.encode()).hexdigest()}",
        fill_payload_fingerprint=hashlib.sha256(f"{runtime_id}|{trade_id}|{update_id}".encode()).hexdigest(),
        fill_index=fill_index,
        fill_count_after=fill_index,
        terminal_fill=True,
        cumulative_price_quantity_after=Decimal("20.00"),
        currency=currency,
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        gross_notional=_money("20.00"),
        settled_notional=_money("20.00"),
        authoritative_fee_total=zero,
        market_fee=zero,
        broker_fee=zero,
        tax=zero,
        commission=zero,
        other_fee=zero,
        reported_broker_fee=None,
        fee_reporting_mode=OnlyBrokerFeeReportingMode.NONE,
        reference_price=_price("10.00"),
        slippage=zero,
        realized_pnl_delta=zero,
        cash_delta=_money("-20.00"),
        fee_instruction_id="fee-instruction",
        fee_authority="NONE",
        fee_status=OnlyFeeStatus.CONFIRMED.value,
        market_fee_schedule_ids=(),
        market_fee_schedule_versions=(),
        broker_fee_schedule_ids=(),
        broker_fee_schedule_versions=(),
        fee_breakdown=OnlyFeeBreakdown.empty(currency, OnlyFeeStatus.CONFIRMED),
        market_profile_id="GENERIC_T0_CASH",
        market_profile_version="1",
        compiled_rule_fingerprint="compiled",
        reference_fingerprint="reference",
        trade_instruction_id="trade-instruction",
        settlement_instruction_id="settlement",
        settlement_status="SETTLED",
        asset_available_on=_day(),
        cash_available_on=_day(),
        legal_settlement_date=_day(),
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
        account_cash_delta=_money("-20.00"),
        account_fee_delta=zero,
        account_realized_pnl_delta=zero,
        ledger_cash_delta=_money("-20.00"),
        ledger_fee_delta=zero,
        ledger_realized_pnl_delta=zero,
        incremental_fee_total=zero,
        order_cumulative_fee_after=zero,
        account_reservation_consumed_delta=_money("20.00"),
        account_reservation_released_delta=zero,
        strategy_reservation_consumed_delta=_money("20.00"),
        strategy_reservation_released_delta=zero,
        risk_reservation_quantity_consumed_delta=_quantity("2"),
        risk_reservation_notional_consumed_delta=_money("20.00"),
        position_cumulative_open_price_quantity_after=Decimal("0"),
        allocation_cumulative_open_price_quantity_after=Decimal("0"),
        position_quantity_before=Decimal("0"),
        position_quantity_after=Decimal("2"),
        allocation_quantity_before=Decimal("0"),
        allocation_quantity_after=Decimal("2"),
        position_cumulative_open_price_quantity_before=Decimal("0"),
        allocation_cumulative_open_price_quantity_before=Decimal("0"),
        released_open_price_quantity=Decimal("0"),
        gross_cash_inflow=zero,
        net_cash_inflow=zero,
        allocation_realized_pnl_delta=zero,
        position_reservation_consumed_delta=_quantity("0"),
        position_closed=False,
        allocation_closed=False,
    )


def only_test_generic_t0_cash_buy_open_projections() -> tuple[OnlyRuntimeProjection, ...]:
    """Return the economically coherent Generic T0 Cash projection set."""

    timestamp = _timestamp()
    order_id = OnlyOrderId("order")
    before_order = OnlyOrderExecutionState(
        order_id,
        OnlyOrderRequestId("request"),
        OnlyClientOrderId("client-order"),
        None,
        _TEST_RUNTIME_ID,
        OnlyClusterId("cluster"),
        OnlyAccountId("account"),
        _instrument(),
        OnlyOrderSide.BUY,
        OnlyOffset.OPEN,
        OnlyOrderType.LIMIT,
        OnlyTimeInForce.DAY,
        _quantity("2"),
        _price("10.00"),
        None,
        None,
        OnlyOrderStatus.ACCEPTED,
        _quantity("0"),
        _quantity("2"),
        None,
        timestamp,
        timestamp,
        timestamp,
        timestamp,
        None,
        None,
        None,
        None,
        None,
        None,
        1,
        6,
        None,
        None,
    )
    after_order = replace(
        before_order,
        status=OnlyOrderStatus.FILLED,
        filled_quantity=_quantity("2"),
        remaining_quantity=_quantity("0"),
        average_fill_price=_price("10.00"),
        fill_count=1,
        cumulative_price_quantity=Decimal("20.00"),
        last_trade_id=_TEST_TRADE_ID,
        filled_at=timestamp,
        version=2,
        last_external_sequence=7,
    )
    fill = OnlyOrderFill(
        _TEST_TRADE_ID,
        order_id,
        _price("10.00"),
        _quantity("2"),
        timestamp,
        timestamp,
        external_sequence=7,
        external_event_id="external",
        reference_price=_price("10.00"),
    )
    position = OnlyPositionExecutionState(
        OnlyPositionId("position"),
        OnlyPositionKey(_TEST_RUNTIME_ID, OnlyAccountId("account"), _instrument()),
        OnlyPositionStatus.OPEN,
        _quantity("2"),
        _quantity("2"),
        _quantity("0"),
        _quantity("0"),
        _quantity("0"),
        _quantity("0"),
        _price("10.00"),
        _money("0.00"),
        _money("0.00"),
        timestamp,
        timestamp,
        None,
        1,
        7,
        (7, timestamp.unix_nanos, str(_TEST_TRADE_ID)),
    )
    allocation = OnlyAllocationExecutionState(
        OnlyPositionAllocationId("allocation"),
        OnlyPositionAllocationKey(
            _TEST_RUNTIME_ID,
            OnlyAccountId("account"),
            OnlyClusterId("cluster"),
            _instrument(),
        ),
        _quantity("2"),
        _quantity("2"),
        _quantity("0"),
        _quantity("0"),
        _quantity("0"),
        _quantity("0"),
        _price("10.00"),
        _money("0.00"),
        _money("0.00"),
        timestamp,
        timestamp,
        None,
        1,
        7,
        (7, timestamp.unix_nanos, str(_TEST_TRADE_ID)),
    )
    settlement = OnlySettlementExecutionState(
        "settlement",
        OnlyAccountId("account"),
        _instrument(),
        order_id,
        str(_TEST_TRADE_ID),
        Decimal("2"),
        _money("20.00"),
        True,
        True,
        True,
        True,
        _day(),
        _day(),
        _day(),
        _day(),
        1,
        0,
    )
    fee = OnlyFeeExecutionState(
        OnlyFeeInstructionReplay(
            "fee-instruction",
            str(_TEST_RUNTIME_ID),
            "cluster",
            "account",
            str(order_id),
            str(_TEST_TRADE_ID),
            "MARKET_RULE",
            "fee-idempotency",
            timestamp,
        ),
        (),
        _money("0.00"),
        OnlyFeeBreakdown.empty(_currency(), OnlyFeeStatus.CONFIRMED),
        1,
        0,
    )
    fee_accrual = OnlyOrderFeeAccrualExecutionState(
        _TEST_RUNTIME_ID,
        OnlyAccountId("account"),
        OnlyClusterId("cluster"),
        order_id,
        _currency(),
        _quantity("2"),
        _money("20.00"),
        _money("0.00"),
        (),
        1,
        _TEST_TRADE_ID,
        timestamp,
        1,
    )
    account_before = _account_state(cash="100.00", market_value="0.00", version=1, sequence=6)
    account_after = _account_state(cash="80.00", market_value="20.00", version=2, sequence=7)
    ledger_before = _ledger_state(cash="100.00", position_cost="0.00", market_value="0.00", version=1)
    ledger_after = _ledger_state(
        cash="80.00",
        position_cost="20.00",
        market_value="20.00",
        version=2,
        with_trade_entry=True,
    )
    account_reservation_before = OnlyAccountCashReservationExecutionState(
        "account-reservation",
        _TEST_RUNTIME_ID,
        OnlyAccountId("account"),
        order_id,
        _money("20.00"),
        _money("0.00"),
        _money("20.00"),
        OnlyAccountReservationState.ACTIVE,
        timestamp,
        timestamp,
        1,
    )
    account_reservation_after = replace(
        account_reservation_before,
        consumed_amount=_money("20.00"),
        remaining_amount=_money("0.00"),
        state=OnlyAccountReservationState.RELEASED,
        version=3,
    )
    ledger_key = _ledger_key()
    strategy_reservation_before = OnlyStrategyCashReservationExecutionState(
        OnlyStrategyCashReservationId("strategy-reservation"),
        ledger_key,
        order_id,
        _money("20.00"),
        _money("0.00"),
        _money("20.00"),
        _money("0.00"),
        _money("20.00"),
        OnlyStrategyCashReservationState.ACTIVE,
        OnlyStrategyCashReservationStage.BROKER_ACKNOWLEDGED,
        timestamp,
        timestamp,
        1,
    )
    strategy_reservation_after = replace(
        strategy_reservation_before,
        consumed_amount=_money("20.00"),
        remaining_amount=_money("0.00"),
        state=OnlyStrategyCashReservationState.RELEASED,
        stage=OnlyStrategyCashReservationStage.RELEASED,
        version=3,
    )
    risk_reservation_before = OnlyRiskReservationExecutionState(
        OnlyRiskReservationId("risk-reservation"),
        OnlyRiskReservationType.ORDER,
        _TEST_RUNTIME_ID,
        OnlyClusterId("cluster"),
        OnlyAccountId("account"),
        _instrument(),
        order_id,
        _quantity("2"),
        _money("20.00"),
        _quantity("0"),
        _money("0.00"),
        _quantity("2"),
        _money("20.00"),
        OnlyRiskReservationState.ACTIVE,
        None,
        timestamp,
        timestamp,
        1,
    )
    risk_reservation_after = replace(
        risk_reservation_before,
        consumed_quantity=_quantity("2"),
        consumed_notional=_money("20.00"),
        remaining_quantity=_quantity("0"),
        remaining_notional=_money("0.00"),
        state=OnlyRiskReservationState.CONSUMED,
        version=2,
    )
    risk_before = OnlyRiskExecutionState(
        OnlyRuntimeId("runtime"),
        OnlyClusterId("cluster"),
        OnlyAccountId("account"),
        timestamp,
        timestamp,
        1,
        OnlyRiskLevel.NORMAL,
        False,
        1,
        1,
        _money("20.00"),
        Decimal("2"),
        _money("80.00"),
        0,
    )
    risk_after = replace(
        risk_before,
        version=2,
        active_order_count=0,
        cluster_active_order_count=0,
        reserved_notional=_money("0.00"),
        reserved_quantity=Decimal(0),
        remaining_order_notional=_money("60.00"),
    )

    projections: tuple[OnlyRuntimeProjection, ...] = (
        OnlyOrderExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.ORDER, 1, str(order_id), before_order, after_order),
            before_order,
            after_order,
            fill,
            _TEST_UPDATE_ID,
        ),
        OnlyPositionExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.POSITION, 2, "position", None, position),
            None,
            position,
            _money("0.00"),
            OnlyPositionExecutionReplayMetadata(1),
        ),
        OnlyAllocationExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.ALLOCATION, 3, "allocation", None, allocation),
            None,
            allocation,
            _money("0.00"),
            OnlyAllocationExecutionReplayMetadata(1),
        ),
        OnlySettlementExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.SETTLEMENT, 4, "settlement", None, settlement),
            None,
            settlement,
            (),
        ),
        OnlyOrderFeeAccrualExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL, 5, str(order_id), None, fee_accrual),
            None,
            fee_accrual,
        ),
        OnlyFeeExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.FEE, 6, "fee-instruction", None, fee),
            None,
            fee,
        ),
        OnlyAccountExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.ACCOUNT, 7, "account", account_before, account_after),
            account_before,
            account_after,
        ),
        OnlyStrategyLedgerExecutionProjection(
            _identity(
                OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
                8,
                "ledger",
                ledger_before,
                ledger_after,
            ),
            ledger_before,
            ledger_after,
        ),
        OnlyAccountCashReservationExecutionProjection(
            _identity(
                OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION,
                9,
                "account-reservation",
                account_reservation_before,
                account_reservation_after,
            ),
            account_reservation_before,
            account_reservation_after,
        ),
        OnlyStrategyCashReservationExecutionProjection(
            _identity(
                OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
                10,
                "strategy-reservation",
                strategy_reservation_before,
                strategy_reservation_after,
            ),
            strategy_reservation_before,
            strategy_reservation_after,
        ),
        OnlyRiskReservationExecutionProjection(
            _identity(
                OnlyRuntimeProjectionComponent.RISK_RESERVATION,
                11,
                "risk-reservation",
                risk_reservation_before,
                risk_reservation_after,
            ),
            risk_reservation_before,
            risk_reservation_after,
        ),
        OnlyRiskExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.RISK, 12, "risk", risk_before, risk_after),
            risk_before,
            risk_after,
        ),
    )
    return tuple(only_with_execution_projection_hash(item) for item in projections)


def only_test_projection_codec_cases() -> tuple[OnlyRuntimeProjection, ...]:
    """Return independent projection cases for union/codec coverage."""

    timestamp = _timestamp()
    order_id = OnlyOrderId("order")
    base = only_test_generic_t0_cash_buy_open_projections()
    position_reservation_before = OnlyPositionReservationExecutionState(
        OnlyPositionReservationId("position-reservation"),
        _TEST_RUNTIME_ID,
        OnlyAccountId("account"),
        OnlyClusterId("cluster"),
        _instrument(),
        OnlyPositionSide.LONG,
        OnlyPositionMode.NETTING,
        order_id,
        _quantity("2"),
        _quantity("2"),
        OnlySettlementBucket.SETTLED,
        OnlyPositionReservationStage.BROKER_ACKNOWLEDGED,
        OnlyPositionReservationState.ACTIVE,
        timestamp,
        timestamp,
        1,
    )
    position_reservation_after = replace(
        position_reservation_before,
        remaining_quantity=_quantity("0"),
        consumed_quantity=_quantity("2"),
        state=OnlyPositionReservationState.CONSUMED,
        version=2,
    )
    margin_before = OnlyMarginExecutionState(
        "margin-instruction",
        OnlyAccountId("account"),
        _instrument(),
        order_id,
        str(_TEST_TRADE_ID),
        "CNY",
        "RESERVE",
        Decimal("10"),
        Decimal("10"),
        Decimal("0"),
        Decimal("0"),
        timestamp,
        1,
    )
    margin_after = replace(margin_before, action="OCCUPY", reserved=Decimal("0"), occupied=Decimal("10"), version=2)
    margin_reservation_before = OnlyMarginReservationExecutionState(
        "margin-reservation",
        _TEST_RUNTIME_ID,
        OnlyAccountId("account"),
        _instrument(),
        order_id,
        _currency(),
        _money("10.00"),
        _money("10.00"),
        _money("0.00"),
        _money("0.00"),
        _money("0.00"),
        OnlyMarginReservationExecutionStatus.ACTIVE,
        OnlyMarginReservationExecutionStage.RESERVED,
        timestamp,
        timestamp,
        1,
    )
    margin_reservation_after = replace(
        margin_reservation_before,
        remaining_reserved_amount=_money("0.00"),
        occupied_amount=_money("10.00"),
        state=OnlyMarginReservationExecutionStatus.OCCUPIED,
        stage=OnlyMarginReservationExecutionStage.OCCUPIED,
        version=2,
    )
    risk_reservation_before = OnlyRiskReservationExecutionState(
        OnlyRiskReservationId("risk-reservation"),
        OnlyRiskReservationType.ORDER,
        _TEST_RUNTIME_ID,
        OnlyClusterId("cluster"),
        OnlyAccountId("account"),
        _instrument(),
        order_id,
        _quantity("2"),
        _money("20.00"),
        _quantity("0"),
        _money("0.00"),
        _quantity("2"),
        _money("20.00"),
        OnlyRiskReservationState.ACTIVE,
        None,
        timestamp,
        timestamp,
        1,
    )
    risk_reservation_after = replace(
        risk_reservation_before,
        consumed_quantity=_quantity("2"),
        consumed_notional=_money("20.00"),
        remaining_quantity=_quantity("0"),
        remaining_notional=_money("0.00"),
        state=OnlyRiskReservationState.CONSUMED,
        version=2,
    )
    risk_before = OnlyRiskExecutionState(
        OnlyRuntimeId("runtime"),
        OnlyClusterId("cluster"),
        OnlyAccountId("account"),
        timestamp,
        timestamp,
        1,
        OnlyRiskLevel.NORMAL,
        False,
        1,
        1,
        _money("20.00"),
        Decimal("2"),
        _money("80.00"),
        0,
    )
    risk_after = replace(
        risk_before,
        version=2,
        active_order_count=0,
        cluster_active_order_count=0,
        reserved_notional=_money("0.00"),
        reserved_quantity=Decimal(0),
        remaining_order_notional=_money("100.00"),
    )
    valuation_before = OnlyValuationExecutionState(
        OnlyAccountId("account"),
        timestamp,
        _money("100.00"),
        _money("0.00"),
        _money("0.00"),
        _money("100.00"),
        1,
    )
    valuation_after = replace(
        valuation_before,
        cash=_money("80.00"),
        position_market_value=_money("20.00"),
        version=2,
    )
    extras: dict[OnlyRuntimeProjectionComponent, OnlyRuntimeProjection] = {
        OnlyRuntimeProjectionComponent.MARGIN: OnlyMarginExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.MARGIN, 1, "margin-instruction", margin_before, margin_after),
            margin_before,
            margin_after,
        ),
        OnlyRuntimeProjectionComponent.POSITION_RESERVATION: OnlyPositionReservationExecutionProjection(
            _identity(
                OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
                1,
                "position-reservation",
                position_reservation_before,
                position_reservation_after,
            ),
            position_reservation_before,
            position_reservation_after,
        ),
        OnlyRuntimeProjectionComponent.MARGIN_RESERVATION: OnlyMarginReservationExecutionProjection(
            _identity(
                OnlyRuntimeProjectionComponent.MARGIN_RESERVATION,
                1,
                "margin-reservation",
                margin_reservation_before,
                margin_reservation_after,
            ),
            margin_reservation_before,
            margin_reservation_after,
        ),
        OnlyRuntimeProjectionComponent.RISK_RESERVATION: OnlyRiskReservationExecutionProjection(
            _identity(
                OnlyRuntimeProjectionComponent.RISK_RESERVATION,
                1,
                "risk-reservation",
                risk_reservation_before,
                risk_reservation_after,
            ),
            risk_reservation_before,
            risk_reservation_after,
        ),
        OnlyRuntimeProjectionComponent.RISK: OnlyRiskExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.RISK, 1, "risk", risk_before, risk_after),
            risk_before,
            risk_after,
        ),
        OnlyRuntimeProjectionComponent.VALUATION: OnlyValuationExecutionProjection(
            _identity(OnlyRuntimeProjectionComponent.VALUATION, 1, "valuation", valuation_before, valuation_after),
            valuation_before,
            valuation_after,
        ),
    }
    by_component = {item.identity.component: item for item in base} | extras
    projections = tuple(
        _resequence_projection(by_component[component], sequence)
        for sequence, component in enumerate(OnlyRuntimeProjectionComponent, start=1)
    )
    return projections


def only_test_generic_t0_cash_buy_open_transaction(
    *,
    prepared_at: OnlyTimestamp | None = None,
    runtime_id: OnlyRuntimeId = _TEST_RUNTIME_ID,
    trade_id: OnlyTradeId = _TEST_TRADE_ID,
    update_id: OnlyBrokerUpdateId = _TEST_UPDATE_ID,
    fill_index: int = 1,
) -> OnlyPreparedRuntimeTransaction:
    fact = only_test_execution_fact_draft(
        runtime_id=runtime_id,
        trade_id=trade_id,
        update_id=update_id,
        fill_index=fill_index,
    )
    projections = only_test_generic_t0_cash_buy_open_projections()
    if runtime_id != _TEST_RUNTIME_ID or trade_id != _TEST_TRADE_ID or update_id != _TEST_UPDATE_ID:
        projections = _rescope_projections(projections, runtime_id, trade_id, update_id)
    transaction_id = only_runtime_transaction_id(
        runtime_id=runtime_id,
        gateway_id=fact.gateway_id,
        account_id=fact.account_id,
        broker_update_id=update_id,
        trade_id=trade_id,
    )
    return OnlyPreparedRuntimeTransaction(
        transaction_id=transaction_id,
        runtime_id=runtime_id,
        operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
        operation_identity=fact.fill_identity,
        account_id=fact.account_id,
        effective_time=fact.ts_event,
        prepared_at=fact.ts_init if prepared_at is None else prepared_at,
        fact_draft=fact,
        projections=projections,
        outbox_events=only_test_execution_events(transaction_id=transaction_id, runtime_id=runtime_id),
        preconditions=only_test_execution_preconditions(projections),
    )


def only_test_execution_preconditions(
    projections: tuple[OnlyRuntimeProjection, ...],
) -> tuple[OnlyRuntimePrecondition, ...]:
    return tuple(
        OnlyRuntimePrecondition(
            item.identity.component,
            item.identity.entity_key,
            item.identity.expected_version,
            item.identity.expected_state_hash,
        )
        for item in projections
    )


def only_test_execution_events(*, transaction_id: str, runtime_id: OnlyRuntimeId) -> tuple[OnlyEvent, ...]:
    factory = OnlyExecutionTransactionEventFactory()
    return tuple(
        factory.create(
            transaction_id=transaction_id,
            event_sequence=index,
            event_type=OnlyEventType(f"TRADE_EVENT_{index}"),
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            engine_id=OnlyEngineId("engine"),
            runtime_id=runtime_id,
            source=OnlyEventSource("execution"),
            payload={"sequence": index},
        )
        for index in (1, 2)
    )


def only_test_rehash(prepared: OnlyPreparedRuntimeTransaction, **changes: object) -> OnlyPreparedRuntimeTransaction:
    return replace(prepared, **changes, authority_hash="", payload_hash="")


def _identity(
    component: OnlyRuntimeProjectionComponent,
    sequence: int,
    entity_key: str,
    before: OnlyDomainModel | None,
    after: OnlyDomainModel,
) -> OnlyRuntimeProjectionIdentity:
    expected_version = 0 if before is None else int(str(before.to_dict()["version"]))
    result_version = int(str(after.to_dict()["version"]))
    return OnlyRuntimeProjectionIdentity(
        component,
        entity_key,
        expected_version,
        result_version,
        only_execution_state_hash(before),
        only_execution_state_hash(after),
        sequence,
        "0" * 64,
    )


def _projection[ProjectionT: OnlyRuntimeProjection](
    projections: tuple[OnlyRuntimeProjection, ...], projection_type: type[ProjectionT]
) -> ProjectionT:
    return next(item for item in projections if isinstance(item, projection_type))


def _resequence_projection(projection: OnlyRuntimeProjection, sequence: int) -> OnlyRuntimeProjection:
    updated = replace(
        projection,
        identity=replace(projection.identity, projection_sequence=sequence, payload_hash="0" * 64),
    )
    return only_with_execution_projection_hash(updated)


def _account_state(*, cash: str, market_value: str, version: int, sequence: int) -> OnlyAccountExecutionState:
    cash_money = _money(cash)
    market_money = _money(market_value)
    zero = _money("0.00")
    return OnlyAccountExecutionState(
        _TEST_RUNTIME_ID,
        OnlyAccountId("account"),
        "gateway",
        OnlyAccountType.CASH,
        _currency(),
        OnlyAccountStatus.ACTIVE,
        cash_money,
        cash_money,
        cash_money,
        zero,
        zero,
        market_money,
        zero,
        zero,
        zero,
        _money(str(cash_money.amount + market_money.amount)),
        _timestamp(),
        _timestamp(),
        _timestamp(),
        version,
        sequence,
        (),
        zero,
        zero,
        zero,
        cash_money,
    )


def _ledger_state(
    *, cash: str, position_cost: str, market_value: str, version: int, with_trade_entry: bool = False
) -> OnlyStrategyLedgerExecutionState:
    zero = _money("0.00")
    entries: tuple[OnlyStrategyCashEntry, ...] = ()
    if with_trade_entry:
        entries = (
            OnlyStrategyCashEntry(
                OnlyStrategyCashEntryId("cash-entry"),
                _TEST_RUNTIME_ID,
                OnlyAccountId("account"),
                OnlyClusterId("cluster"),
                _currency(),
                _money("-20.00"),
                OnlyStrategyCashEntryType.BUY_SETTLEMENT,
                OnlyOrderId("order"),
                _TEST_TRADE_ID,
                OnlyStrategyCashReservationId("strategy-reservation"),
                None,
                _timestamp(),
                _timestamp(),
                7,
            ),
        )
    return OnlyStrategyLedgerExecutionState(
        OnlyStrategyLedgerId("ledger"),
        _ledger_key(),
        OnlyStrategyLedgerStatus.ACTIVE,
        _money("100.00"),
        zero,
        _money(cash),
        zero,
        _money(cash),
        _money(position_cost),
        _money(market_value),
        zero,
        zero,
        zero,
        _money(str(Decimal(cash) + Decimal(market_value))),
        entries,
        (),
        _timestamp(),
        _timestamp(),
        _timestamp(),
        version,
        7 if with_trade_entry else 6,
        (7, _timestamp().unix_nanos, str(_TEST_TRADE_ID)) if with_trade_entry else None,
    )


def _rescope_projections(
    projections: tuple[OnlyRuntimeProjection, ...],
    runtime_id: OnlyRuntimeId,
    trade_id: OnlyTradeId,
    update_id: OnlyBrokerUpdateId,
) -> tuple[OnlyRuntimeProjection, ...]:
    if runtime_id != _TEST_RUNTIME_ID:
        raise ValueError("custom Runtime fixture scope is not supported")
    result: list[OnlyRuntimeProjection] = []
    for projection in projections:
        updated: OnlyRuntimeProjection = projection
        if isinstance(projection, OnlyOrderExecutionProjection):
            after = replace(projection.after, last_trade_id=trade_id)
            identity = replace(
                projection.identity,
                result_state_hash=only_execution_state_hash(after),
                payload_hash="0" * 64,
            )
            updated = replace(
                projection,
                identity=identity,
                after=after,
                fill=replace(projection.fill, trade_id=trade_id),
                broker_update_id=update_id,
            )
        elif isinstance(projection, OnlySettlementExecutionProjection):
            after = replace(projection.after, source_trade_id=str(trade_id))
            updated = _replace_projection_after(projection, after)
        elif isinstance(projection, OnlyFeeExecutionProjection):
            after = replace(
                projection.after,
                instruction=replace(projection.after.instruction, trade_id=str(trade_id)),
            )
            updated = _replace_projection_after(projection, after)
        elif isinstance(projection, OnlyStrategyLedgerExecutionProjection):
            entries = tuple(replace(entry, trade_id=trade_id) for entry in projection.after.cash_entries)
            after = replace(
                projection.after,
                cash_entries=entries,
                last_trade_order=(7, _timestamp().unix_nanos, str(trade_id)),
            )
            updated = _replace_projection_after(projection, after)
        result.append(only_with_execution_projection_hash(updated))
    return tuple(result)


def _replace_projection_after[ProjectionT: OnlyRuntimeProjection](
    projection: ProjectionT, after: object
) -> ProjectionT:
    if not hasattr(after, "version"):
        raise TypeError("fixture after state must be versioned")
    identity = replace(
        projection.identity,
        result_state_hash=only_execution_state_hash(after),  # type: ignore[arg-type]
        payload_hash="0" * 64,
    )
    return replace(projection, identity=identity, after=after)  # type: ignore[arg-type,return-value]


def _currency() -> OnlyCurrency:
    return OnlyCurrency("CNY", 2, OnlyCurrencyType.FIAT)


def _money(value: str) -> OnlyMoney:
    return OnlyMoney(Decimal(value), _currency())


def _quantity(value: str) -> OnlyQuantity:
    return OnlyQuantity(Decimal(value), 0)


def _price(value: str) -> OnlyPrice:
    return OnlyPrice(Decimal(value), 2)


def _timestamp() -> OnlyTimestamp:
    return OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))


def _day() -> OnlyTradingDay:
    return OnlyTradingDay(date(2026, 1, 1))


def _instrument() -> OnlyInstrumentId:
    return OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))


def _ledger_key() -> OnlyStrategyLedgerKey:
    return OnlyStrategyLedgerKey(
        _TEST_RUNTIME_ID,
        OnlyAccountId("account"),
        OnlyClusterId("cluster"),
        _currency(),
    )
