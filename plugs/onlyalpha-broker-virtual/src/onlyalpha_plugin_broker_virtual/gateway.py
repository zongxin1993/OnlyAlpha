"""Deterministic Virtual Broker implementing the normalized Broker Ports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal

from onlyalpha.broker.capabilities import OnlyBrokerCapabilities
from onlyalpha.broker.enums import OnlyBrokerCapability, OnlyBrokerConnectionState, OnlyBrokerOperationStatus
from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.broker.models import (
    OnlyBrokerAccountSnapshot,
    OnlyBrokerBalanceSnapshot,
    OnlyBrokerCancelRequest,
    OnlyBrokerCancelResult,
    OnlyBrokerConnectionResult,
    OnlyBrokerConnectionSnapshot,
    OnlyBrokerOrderRequest,
    OnlyBrokerOrderSnapshot,
    OnlyBrokerOrderSubmitResult,
    OnlyBrokerPositionSnapshot,
    OnlyBrokerQuery,
    OnlyBrokerTradeSnapshot,
)
from onlyalpha.broker.updates import (
    OnlyBrokerConnectionUpdate,
    OnlyBrokerInboundUpdate,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderExpiredUpdate,
    OnlyBrokerOrderRejectedUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.enums import OnlyLiquiditySide, OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRejection
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueOrderId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.fee.evidence import OnlyExternalFeeEvidence
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor
from onlyalpha.plugin.lifecycle import (
    OnlyPluginHealth,
    OnlyPluginHealthStatus,
    OnlyPluginLifecycleState,
)
from onlyalpha_plugin_broker_virtual.config import OnlyVirtualBrokerConfig
from onlyalpha_plugin_broker_virtual.descriptor import ONLY_VIRTUAL_PLUGIN_DESCRIPTOR
from onlyalpha_plugin_broker_virtual.fill_plan import (
    OnlyVirtualFillDispatchMode,
    OnlyVirtualFillPlanStatus,
    OnlyVirtualFillPlanStep,
    OnlyVirtualOrderFillPlan,
    only_create_virtual_order_fill_plan,
)
from onlyalpha_plugin_broker_virtual.fill_plan_store import OnlyVirtualFillPlanStore
from onlyalpha_plugin_broker_virtual.latency import OnlyLatencyModel, OnlyZeroLatencyModel
from onlyalpha_plugin_broker_virtual.matching import OnlyMatchingEngine, OnlyNextBarMatchingEngine
from onlyalpha_plugin_broker_virtual.scheduler import OnlyVirtualBrokerScheduler
from onlyalpha_plugin_broker_virtual.slippage import OnlyNoSlippageModel, OnlySlippageModel
from onlyalpha_plugin_broker_virtual.stores import (
    OnlyVirtualBrokerAccountStore,
    OnlyVirtualBrokerOrderStore,
    OnlyVirtualBrokerTradeStore,
)
from onlyalpha_plugin_broker_virtual.submission_control import (
    OnlyVirtualSubmissionAction,
    OnlyVirtualSubmissionControl,
    only_virtual_submission_control_from_checkpoint,
    only_virtual_submission_control_to_checkpoint,
)


class OnlyVirtualBrokerGateway:
    """Virtual external system; it never imports or shares a Runtime Manager."""

    @property
    def checkpoint_schema_version(self) -> int:
        return 3

    def __init__(
        self,
        config: OnlyVirtualBrokerConfig,
        runtime_id: OnlyRuntimeId,
        clock: OnlyClock,
        inbound: Callable[[OnlyBrokerInboundUpdate], None],
        *,
        matching_engine: OnlyMatchingEngine | None = None,
        slippage_model: OnlySlippageModel | None = None,
        latency_model: OnlyLatencyModel | None = None,
        scheduler: OnlyVirtualBrokerScheduler | None = None,
    ) -> None:
        self.config = config
        self.runtime_id = runtime_id
        self._clock = clock
        self._inbound = inbound
        # Fill quantity authority is always the normalized order Fill Plan. Matching owns price eligibility only.
        self._matching = matching_engine or OnlyNextBarMatchingEngine()
        self._slippage = slippage_model or config.slippage_model or OnlyNoSlippageModel()
        self._latency = latency_model or config.latency_model or OnlyZeroLatencyModel()
        self.scheduler = scheduler or OnlyVirtualBrokerScheduler()
        self.account_store = OnlyVirtualBrokerAccountStore(
            config.gateway_id,
            config.account_id,
            config.base_currency,
            config.initial_cash,
        )
        self.order_store = OnlyVirtualBrokerOrderStore()
        self.trade_store = OnlyVirtualBrokerTradeStore()
        self.fill_plan_store = OnlyVirtualFillPlanStore()
        self._state = OnlyBrokerConnectionState.DISCONNECTED
        self._state_time = self._now()
        self._source_sequence = 0
        self._venue_order_sequence = 0
        self._trade_sequence = 0
        self._bar_sequence = 0
        self._accepted_bar: dict[OnlyOrderId, int] = {}
        self._current_day: date | None = None
        self._latest_bars: dict[OnlyInstrumentId, OnlyBar] = {}
        self._plugin_state = OnlyPluginLifecycleState.CREATED

    @property
    def plugin_descriptor(self) -> OnlyPluginDescriptor:
        return ONLY_VIRTUAL_PLUGIN_DESCRIPTOR

    @property
    def plugin_resource_id(self) -> str:
        return str(self.config.gateway_id)

    @property
    def state(self) -> OnlyPluginLifecycleState:
        return self._plugin_state

    def initialize(self) -> None:
        if self._plugin_state is OnlyPluginLifecycleState.CREATED:
            self._plugin_state = OnlyPluginLifecycleState.INITIALIZED

    @property
    def capabilities(self) -> OnlyBrokerCapabilities:
        return OnlyBrokerCapabilities(frozenset(OnlyBrokerCapability))

    def query_fee_evidence(self, account_id: OnlyAccountId) -> tuple[OnlyExternalFeeEvidence, ...]:
        self.capabilities.require(OnlyBrokerCapability.QUERY_FEE_EVIDENCE)
        if account_id != self.config.account_id:
            raise ValueError("Virtual Broker account scope mismatch")
        return ()

    def connect(self) -> OnlyBrokerConnectionResult:
        if self._plugin_state is OnlyPluginLifecycleState.CREATED:
            self.initialize()
        self._plugin_state = OnlyPluginLifecycleState.CONNECTING
        self._state = OnlyBrokerConnectionState.CONNECTED
        self._state_time = self._now()
        self._emit(
            OnlyBrokerConnectionUpdate,
            self._state_time,
            str(self.config.gateway_id),
            "connect",
            state=self._state,
        )
        self._plugin_state = OnlyPluginLifecycleState.CONNECTED
        return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.RECEIVED, self.connection_snapshot())

    def start(self) -> None:
        if self._plugin_state is OnlyPluginLifecycleState.INITIALIZED:
            self.connect()
        if self._state is OnlyBrokerConnectionState.CONNECTED:
            result = self.authenticate()
            if result.status is not OnlyBrokerOperationStatus.RECEIVED:
                self._plugin_state = OnlyPluginLifecycleState.FAILED
                raise RuntimeError("Virtual Broker authentication failed")
        if self._state is OnlyBrokerConnectionState.READY:
            self._plugin_state = OnlyPluginLifecycleState.RUNNING

    def stop(self) -> None:
        if self._plugin_state is OnlyPluginLifecycleState.STOPPED:
            return
        self._plugin_state = OnlyPluginLifecycleState.STOPPING
        if self._state is not OnlyBrokerConnectionState.DISCONNECTED:
            self.disconnect()
        self._plugin_state = OnlyPluginLifecycleState.STOPPED

    def close(self) -> None:
        self.stop()

    def health(self) -> OnlyPluginHealth:
        if self._plugin_state is OnlyPluginLifecycleState.RUNNING:
            return OnlyPluginHealth(OnlyPluginHealthStatus.HEALTHY)
        if self._plugin_state is OnlyPluginLifecycleState.STOPPED:
            return OnlyPluginHealth(OnlyPluginHealthStatus.STOPPED)
        if self._plugin_state is OnlyPluginLifecycleState.FAILED:
            return OnlyPluginHealth(OnlyPluginHealthStatus.UNHEALTHY, "Virtual Broker failed")
        return OnlyPluginHealth(OnlyPluginHealthStatus.UNKNOWN)

    def authenticate(self) -> OnlyBrokerConnectionResult:
        if self._state is not OnlyBrokerConnectionState.CONNECTED:
            return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.NOT_READY, self.connection_snapshot())
        self._state = OnlyBrokerConnectionState.READY
        self._state_time = self._now()
        self._emit(
            OnlyBrokerConnectionUpdate,
            self._state_time,
            str(self.config.gateway_id),
            "authenticate",
            state=self._state,
        )
        return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.RECEIVED, self.connection_snapshot())

    def disconnect(self) -> OnlyBrokerConnectionResult:
        self._state = OnlyBrokerConnectionState.DISCONNECTED
        self._state_time = self._now()
        self._emit(
            OnlyBrokerConnectionUpdate,
            self._state_time,
            str(self.config.gateway_id),
            "disconnect",
            state=self._state,
        )
        return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.RECEIVED, self.connection_snapshot())

    def connection_snapshot(self) -> OnlyBrokerConnectionSnapshot:
        return OnlyBrokerConnectionSnapshot(self.config.gateway_id, self._state, self._state_time)

    def submit_order(self, request: OnlyBrokerOrderRequest) -> OnlyBrokerOrderSubmitResult:
        if self._state is not OnlyBrokerConnectionState.READY:
            return OnlyBrokerOrderSubmitResult(
                False,
                OnlyBrokerOperationStatus.NOT_READY,
                request.gateway_request_id,
                request.client_order_id,
                "Broker is not READY",
            )
        if request.account_id != self.config.account_id:
            return OnlyBrokerOrderSubmitResult(
                False,
                OnlyBrokerOperationStatus.REJECTED,
                request.gateway_request_id,
                request.client_order_id,
                "unknown Broker account",
            )
        self._venue_order_sequence += 1
        submission_index = self._venue_order_sequence
        submission_control = self.config.submission_simulation.control_for(submission_index)
        venue_order_id = OnlyVenueOrderId(f"virtual-order-{self._venue_order_sequence:08d}")
        order = OnlyBrokerOrderSnapshot(
            self.config.gateway_id,
            request.account_id,
            request.order_id,
            request.client_order_id,
            venue_order_id,
            request.instrument_id,
            request.side,
            request.offset,
            request.order_type,
            request.quantity,
            type(request.quantity)(Decimal(0), request.quantity.precision),
            request.price,
            OnlyOrderStatus.SUBMITTED,
            request.submitted_at,
            request.submitted_at,
            self._next_sequence(),
        )
        self.order_store.save(order)
        due = request.submitted_at.unix_nanos + self._latency.submit_latency_ns + self._latency.acceptance_latency_ns
        action_payload = {
            "causation_id": request.gateway_request_id.value,
            "control": only_virtual_submission_control_to_checkpoint(submission_control),
            "order_id": str(order.order_id),
            "submission_index": submission_index,
            "type": "SUBMISSION",
        }
        self.scheduler.schedule(
            due,
            lambda: self._apply_submission_control(
                order,
                request.gateway_request_id.value,
                submission_control,
            ),
            checkpoint_payload=action_payload,
        )
        return OnlyBrokerOrderSubmitResult(
            True,
            OnlyBrokerOperationStatus.RECEIVED,
            request.gateway_request_id,
            request.client_order_id,
        )

    def cancel_order(self, request: OnlyBrokerCancelRequest) -> OnlyBrokerCancelResult:
        if self._state is not OnlyBrokerConnectionState.READY:
            return OnlyBrokerCancelResult(
                False, OnlyBrokerOperationStatus.NOT_READY, request.gateway_request_id, "Broker is not READY"
            )
        try:
            order = self.order_store.require(request.order_id)
        except KeyError:
            return OnlyBrokerCancelResult(
                False, OnlyBrokerOperationStatus.REJECTED, request.gateway_request_id, "unknown Broker order"
            )
        if order.status in {
            OnlyOrderStatus.CANCELLED,
            OnlyOrderStatus.EXPIRED,
            OnlyOrderStatus.FILLED,
            OnlyOrderStatus.REJECTED,
        }:
            return OnlyBrokerCancelResult(
                False, OnlyBrokerOperationStatus.REJECTED, request.gateway_request_id, "Broker order is terminal"
            )
        due = request.requested_at.unix_nanos + self._latency.cancel_latency_ns
        action_payload = {
            "causation_id": request.gateway_request_id.value,
            "order_id": str(request.order_id),
            "type": "CANCEL",
        }
        self.scheduler.schedule(
            due,
            lambda: self._cancel(request.order_id, request.gateway_request_id.value),
            checkpoint_payload=action_payload,
        )
        return OnlyBrokerCancelResult(True, OnlyBrokerOperationStatus.RECEIVED, request.gateway_request_id)

    def on_bar(self, bar: OnlyBar) -> None:
        # Deliver cancellations/acceptances due at this Clock instant before matching.
        self.run_due()
        self._bar_sequence += 1
        self.account_store.mark(bar.instrument_id, bar.close)
        if self._current_day is None:
            self._current_day = bar.trading_day
        elif bar.trading_day > self._current_day:
            self._current_day = bar.trading_day
        timestamp = OnlyTimestamp.from_datetime(bar.ts_event)
        for order in self.order_store.open(self.config.account_id):
            if order.status not in {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PARTIALLY_FILLED}:
                continue
            if self._accepted_bar.get(order.order_id, self._bar_sequence) >= self._bar_sequence:
                continue
            plan = self.fill_plan_store.require(order.order_id)
            if plan.status is not OnlyVirtualFillPlanStatus.ACTIVE:
                continue
            result = self._matching.match(order, bar)
            if not result.matched or result.price is None:
                continue
            while True:
                current = self.fill_plan_store.require(order.order_id)
                step = current.next_step
                elapsed_bar_offset = self._bar_sequence - current.accepted_bar_sequence
                if step is None or step.bar_offset > elapsed_bar_offset:
                    break
                latest_order = self.order_store.require(order.order_id)
                self._execute_plan_step(latest_order, current, step, result.price, timestamp)
                if current.dispatch_mode is OnlyVirtualFillDispatchMode.ONE_PER_BAR:
                    break
        self._latest_bars[bar.instrument_id] = bar
        self.run_due()

    def run_due(self) -> int:
        return self.scheduler.run_due(self._clock.timestamp_ns())

    def query_account(self, account_id: OnlyAccountId) -> OnlyBrokerAccountSnapshot:
        self._require_account(account_id)
        return self.account_store.account_snapshot(self._now())

    def query_balances(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerBalanceSnapshot, ...]:
        snapshot = self.query_account(account_id)
        return (
            OnlyBrokerBalanceSnapshot(
                self.config.base_currency,
                snapshot.ledger_cash,
                snapshot.trade_available_cash,
                snapshot.order_reserved_cash,
            ),
        )

    def query_positions(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerPositionSnapshot, ...]:
        self._require_account(account_id)
        return self.account_store.position_snapshots(self._now())

    def query_open_orders(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        self._require_account(account_id)
        return self.order_store.open(account_id)

    def query_orders(
        self, account_id: OnlyAccountId, query: OnlyBrokerQuery | None = None
    ) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        self._require_account(account_id)
        values = self.order_store.list(account_id)
        return (
            values
            if query is None or query.since_sequence is None
            else tuple(item for item in values if item.source_sequence >= query.since_sequence)
        )

    def query_trades(
        self, account_id: OnlyAccountId, query: OnlyBrokerQuery | None = None
    ) -> tuple[OnlyBrokerTradeSnapshot, ...]:
        self._require_account(account_id)
        values = self.trade_store.list(account_id)
        return (
            values
            if query is None or query.since_sequence is None
            else tuple(item for item in values if item.source_sequence >= query.since_sequence)
        )

    def _apply_submission_control(
        self,
        submitted: OnlyBrokerOrderSnapshot,
        causation_id: str,
        control: OnlyVirtualSubmissionControl | None,
    ) -> None:
        if control is None:
            self._accept(submitted, causation_id)
            return
        if control.action is OnlyVirtualSubmissionAction.REJECT_BEFORE_ACCEPTED:
            rejection_code = control.effective_rejection_code
            if rejection_code is None:
                raise RuntimeError("VIRTUAL_SUBMISSION_REJECTION_CODE_MISSING")
            current = self.order_store.require(submitted.order_id)
            if current.status is OnlyOrderStatus.SUBMITTED:
                self._reject(
                    current,
                    causation_id,
                    control.effective_reason,
                    code=rejection_code,
                )
            return
        if control.action is OnlyVirtualSubmissionAction.ACCEPT_THEN_EXPIRE:
            self._accept(submitted, causation_id)
            current = self.order_store.require(submitted.order_id)
            if current.status is OnlyOrderStatus.ACCEPTED:
                self._expire(current, causation_id, control.effective_reason)
            return
        raise RuntimeError("VIRTUAL_SUBMISSION_ACTION_UNSUPPORTED")

    def _accept(self, submitted: OnlyBrokerOrderSnapshot, causation_id: str) -> None:
        current = self.order_store.require(submitted.order_id)
        if current.status is not OnlyOrderStatus.SUBMITTED:
            return
        latest_bar = self._latest_bars.get(current.instrument_id)
        price = current.price if current.price is not None else latest_bar.close if latest_bar is not None else None
        if price is None:
            self._reject(current, causation_id, "MARKET order requires a reference Bar before acceptance")
            return
        required = price.value * current.remaining_quantity.value
        try:
            plan = only_create_virtual_order_fill_plan(
                gateway_id=str(self.config.gateway_id),
                account_id=current.account_id,
                order_id=current.order_id,
                venue_order_id=current.venue_order_id,
                original_quantity=current.quantity,
                accepted_bar_sequence=self._bar_sequence,
                mode=self.config.effective_fill_schedule_mode,
                dispatch_mode=self.config.fill_dispatch_mode,
                schedule_steps=self.config.fill_schedule_steps,
                maximum_fill_quantity=self.config.maximum_fill_quantity,
            )
        except ValueError as exc:
            self._reject(current, causation_id, str(exc))
            return
        closes = current.offset in {OnlyOffset.CLOSE, OnlyOffset.CLOSE_TODAY, OnlyOffset.CLOSE_YESTERDAY}
        reservable = (
            True
            if current.offset is OnlyOffset.OPEN and current.side is OnlyOrderSide.SELL
            else self.account_store.reserve_sell(current.instrument_id, current.remaining_quantity.value)
            if closes or current.side is OnlyOrderSide.SELL
            else self.account_store.reserve_buy(required)
        )
        if not reservable:
            self._reject(current, causation_id, "insufficient Broker cash or settled Position")
            return
        now = self._now()
        accepted_sequence = self._next_sequence()
        accepted = replace(
            current,
            price=price,
            status=OnlyOrderStatus.ACCEPTED,
            updated_at=now,
            source_sequence=accepted_sequence,
        )
        self.order_store.save(accepted)
        self.fill_plan_store.save(plan)
        self._accepted_bar[accepted.order_id] = self._bar_sequence
        self._emit(
            OnlyBrokerOrderAcceptedUpdate,
            now,
            str(accepted.order_id),
            causation_id,
            emitted_sequence=accepted_sequence,
            order_id=accepted.order_id,
            venue_order_id=accepted.venue_order_id,
        )

    def _reject(
        self,
        order: OnlyBrokerOrderSnapshot,
        causation_id: str,
        message: str,
        *,
        code: str = "BROKER_REJECTED",
    ) -> None:
        now = self._now()
        rejected_sequence = self._next_sequence()
        rejected = replace(order, status=OnlyOrderStatus.REJECTED, updated_at=now, source_sequence=rejected_sequence)
        self.order_store.save(rejected)
        self._emit(
            OnlyBrokerOrderRejectedUpdate,
            now,
            str(order.order_id),
            causation_id,
            emitted_sequence=rejected_sequence,
            order_id=order.order_id,
            rejection=OnlyOrderRejection(code, message),
        )

    def _expire(self, order: OnlyBrokerOrderSnapshot, causation_id: str, reason: str) -> None:
        current = self.order_store.require(order.order_id)
        if current.status not in {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PARTIALLY_FILLED}:
            return
        plan = self.fill_plan_store.require(current.order_id)
        if plan.status is not OnlyVirtualFillPlanStatus.ACTIVE:
            raise RuntimeError("VIRTUAL_FILL_PLAN_ORDER_STATUS_CONFLICT")
        self.account_store.release_order(current)
        now = self._now()
        expired_sequence = self._next_sequence()
        expired = replace(
            current,
            status=OnlyOrderStatus.EXPIRED,
            updated_at=now,
            source_sequence=expired_sequence,
        )
        self.order_store.save(expired)
        self.fill_plan_store.expire(current.order_id)
        self._emit(
            OnlyBrokerOrderExpiredUpdate,
            now,
            str(current.order_id),
            causation_id,
            emitted_sequence=expired_sequence,
            metadata={"reason": reason},
            order_id=current.order_id,
        )

    def _cancel(self, order_id: object, causation_id: str) -> None:
        order = self.order_store.require(order_id)  # type: ignore[arg-type]
        if order.status not in {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PARTIALLY_FILLED}:
            return
        plan = self.fill_plan_store.require(order.order_id)
        if plan.status is not OnlyVirtualFillPlanStatus.ACTIVE:
            raise RuntimeError("VIRTUAL_FILL_PLAN_ORDER_STATUS_CONFLICT")
        self.account_store.release_order(order)
        now = self._now()
        cancelled_sequence = self._next_sequence()
        cancelled = replace(order, status=OnlyOrderStatus.CANCELLED, updated_at=now, source_sequence=cancelled_sequence)
        self.order_store.save(cancelled)
        self.fill_plan_store.cancel(order.order_id)
        self._emit(
            OnlyBrokerOrderCancelledUpdate,
            now,
            str(order.order_id),
            causation_id,
            emitted_sequence=cancelled_sequence,
            order_id=order.order_id,
        )

    def _execute(
        self, order: OnlyBrokerOrderSnapshot, raw_price: object, quantity: object, timestamp: OnlyTimestamp
    ) -> None:
        assert isinstance(raw_price, OnlyPrice) and isinstance(quantity, OnlyQuantity)
        plan = self.fill_plan_store.require(order.order_id)
        step = plan.next_step
        if step is None or step.quantity != quantity:
            raise ValueError("VIRTUAL_FILL_PLAN_STEP_QUANTITY_CONFLICT")
        self._execute_plan_step(order, plan, step, raw_price, timestamp)

    def _execute_plan_step(
        self,
        order: OnlyBrokerOrderSnapshot,
        plan: OnlyVirtualOrderFillPlan,
        step: OnlyVirtualFillPlanStep,
        raw_price: OnlyPrice,
        timestamp: OnlyTimestamp,
    ) -> None:
        order = self.order_store.require(order.order_id)
        plan = self.fill_plan_store.require(order.order_id)
        if order.status not in {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PARTIALLY_FILLED}:
            raise ValueError("VIRTUAL_FILL_ORDER_NOT_OPEN")
        if plan.status is not OnlyVirtualFillPlanStatus.ACTIVE or plan.next_step != step:
            raise ValueError("VIRTUAL_FILL_PLAN_CURSOR_CONFLICT")
        quantity = step.quantity
        if quantity.value > order.remaining_quantity.value:
            raise ValueError("VIRTUAL_FILL_PLAN_OVERFILL")
        if plan.executed_quantity != order.filled_quantity or plan.remaining_quantity != order.remaining_quantity:
            raise ValueError("VIRTUAL_FILL_PLAN_ORDER_AUTHORITY_CONFLICT")
        price = self._slippage.apply(order.side, raw_price)
        if order.order_type is OnlyOrderType.LIMIT and order.price is not None:
            price = OnlyPrice(
                min(price.value, order.price.value)
                if order.side is OnlyOrderSide.BUY
                else max(price.value, order.price.value),
                max(price.precision, order.price.precision),
            )
        # This is an external-account projection, not a second fee authority.
        # Runtime resolves and applies the authoritative local fee.
        simulated_broker_fee = Decimal(0)
        self._trade_sequence += 1
        trade_id = OnlyTradeId(f"virtual-trade-{self._trade_sequence:08d}")
        venue_trade_id = OnlyVenueTradeId(f"virtual-venue-trade-{self._trade_sequence:08d}")
        asset_available = True
        fill_sequence = self._next_sequence()
        fill = OnlyOrderFill(
            trade_id=trade_id,
            order_id=order.order_id,
            price=price,
            quantity=quantity,
            ts_event=timestamp,
            ts_init=timestamp,
            venue_trade_id=venue_trade_id,
            venue_order_id=order.venue_order_id,
            liquidity_side=OnlyLiquiditySide.TAKER,
            external_sequence=fill_sequence,
            external_event_id=f"virtual-fill-{self._trade_sequence:08d}",
            reference_price=raw_price,
        )
        reserved = (order.price.value if order.price is not None else price.value) * quantity.value
        if order.side is OnlyOrderSide.BUY and order.offset in {
            OnlyOffset.CLOSE,
            OnlyOffset.CLOSE_TODAY,
            OnlyOffset.CLOSE_YESTERDAY,
        }:
            self.account_store.apply_short_close(
                order.instrument_id,
                quantity.value,
                price,
                simulated_broker_fee,
            )
        elif order.side is OnlyOrderSide.BUY:
            self.account_store.apply_buy(
                order.instrument_id,
                quantity.value,
                price,
                reserved,
                simulated_broker_fee,
                quantity.precision,
                asset_available=asset_available,
            )
        elif order.offset is OnlyOffset.OPEN:
            self.account_store.apply_short_open(
                order.instrument_id,
                quantity.value,
                price,
                simulated_broker_fee,
                quantity.precision,
            )
        else:
            self.account_store.apply_sell(order.instrument_id, quantity.value, price, simulated_broker_fee)
        filled = type(order.filled_quantity)(
            order.filled_quantity.value + quantity.value, order.filled_quantity.precision
        )
        status = OnlyOrderStatus.FILLED if filled.value == order.quantity.value else OnlyOrderStatus.PARTIALLY_FILLED
        updated = replace(
            order,
            filled_quantity=filled,
            status=status,
            updated_at=timestamp,
            source_sequence=fill_sequence,
        )
        self.order_store.save(updated)
        trade = OnlyBrokerTradeSnapshot(self.config.gateway_id, self.config.account_id, trade_id, fill, fill_sequence)
        self.trade_store.save(trade)
        updated_plan = self.fill_plan_store.advance(order.order_id)
        if (status is OnlyOrderStatus.FILLED) != (updated_plan.status is OnlyVirtualFillPlanStatus.COMPLETED):
            raise RuntimeError("VIRTUAL_FILL_PLAN_ORDER_TERMINAL_CONFLICT")

        def publish() -> None:
            self._emit(
                OnlyBrokerTradeUpdate,
                timestamp,
                str(order.order_id),
                str(order.order_id),
                emitted_sequence=fill_sequence,
                order_id=order.order_id,
                fill=fill,
            )

        action_payload = {
            "fill": fill.to_json(),
            "order_id": str(order.order_id),
            "plan_id": plan.plan_id,
            "plan_step_index": step.step_index,
            "sequence": fill_sequence,
            "timestamp_ns": timestamp.unix_nanos,
            "type": "PUBLISH_FILL",
        }
        self.scheduler.schedule(
            timestamp.unix_nanos + self._latency.fill_latency_ns,
            publish,
            checkpoint_payload=action_payload,
        )

    def capture_checkpoint(self) -> object:
        return {
            "schema_version": 3,
            "accepted_bar": [
                [str(order_id), sequence]
                for order_id, sequence in sorted(self._accepted_bar.items(), key=lambda item: str(item[0]))
            ],
            "account": self.account_store.capture_checkpoint(),
            "bar_sequence": self._bar_sequence,
            "connection_state": self._state.value,
            "current_day": None if self._current_day is None else self._current_day.isoformat(),
            "fill_plans": self.fill_plan_store.capture_checkpoint(),
            "latest_bars": [
                [instrument_id.to_json(), bar.to_json()]
                for instrument_id, bar in sorted(self._latest_bars.items(), key=lambda item: str(item[0]))
            ],
            "orders": self.order_store.capture_checkpoint(),
            "plugin_state": self._plugin_state.value,
            "scheduler": self.scheduler.capture_checkpoint(),
            "simulation_fingerprint": self.config.submission_simulation.fingerprint,
            "source_sequence": self._source_sequence,
            "state_time_ns": self._state_time.unix_nanos,
            "trade_sequence": self._trade_sequence,
            "trades": self.trade_store.capture_checkpoint(),
            "venue_order_sequence": self._venue_order_sequence,
        }

    def restore_checkpoint(self, payload: object) -> None:
        try:
            if not isinstance(payload, dict):
                raise ValueError("Virtual Broker checkpoint must be an object")
            if payload.get("schema_version") != 3:
                raise ValueError("VIRTUAL_BROKER_CHECKPOINT_SCHEMA_UNSUPPORTED")
            if payload.get("simulation_fingerprint") != self.config.submission_simulation.fingerprint:
                raise ValueError("VIRTUAL_BROKER_SIMULATION_FINGERPRINT_CONFLICT")
            self.account_store.restore_checkpoint(payload["account"])
            self.order_store.restore_checkpoint(payload["orders"])
            self.trade_store.restore_checkpoint(payload["trades"])
            self.fill_plan_store.restore_checkpoint(payload["fill_plans"])
            self._accepted_bar = {
                OnlyOrderId(str(order_id)): int(sequence) for order_id, sequence in payload["accepted_bar"]
            }
            self._bar_sequence = int(payload["bar_sequence"])
            self._state = OnlyBrokerConnectionState(str(payload["connection_state"]))
            self._state_time = OnlyTimestamp.from_unix_nanos(int(payload["state_time_ns"]))
            current_day = payload["current_day"]
            self._current_day = None if current_day is None else date.fromisoformat(str(current_day))
            self._latest_bars = {
                OnlyInstrumentId.from_json(str(instrument_id)): OnlyBar.from_json(str(bar))
                for instrument_id, bar in payload["latest_bars"]
            }
            self._plugin_state = OnlyPluginLifecycleState(str(payload["plugin_state"]))
            self._source_sequence = int(payload["source_sequence"])
            self._venue_order_sequence = int(payload["venue_order_sequence"])
            self._trade_sequence = int(payload["trade_sequence"])
            self.scheduler.restore_checkpoint(payload["scheduler"], self._resolve_scheduled_action)
            self._validate_checkpoint_authority()
        except Exception:
            self._state = OnlyBrokerConnectionState.FAILED
            self._plugin_state = OnlyPluginLifecycleState.FAILED
            raise

    def _validate_checkpoint_authority(self) -> None:
        orders = {item.order_id: item for item in self.order_store.list(self.config.account_id)}
        trades = self.trade_store.all()
        trades_by_order: dict[OnlyOrderId, list[OnlyBrokerTradeSnapshot]] = {}
        for trade in trades:
            trades_by_order.setdefault(trade.fill.order_id, []).append(trade)
        for plan in self.fill_plan_store.list():
            order = orders.get(plan.order_id)
            if order is None or plan.venue_order_id != order.venue_order_id or plan.original_quantity != order.quantity:
                raise ValueError("VIRTUAL_BROKER_CHECKPOINT_AUTHORITY_CONFLICT")
            if plan.executed_quantity != order.filled_quantity or plan.remaining_quantity != order.remaining_quantity:
                raise ValueError("VIRTUAL_BROKER_CHECKPOINT_AUTHORITY_CONFLICT")
            expected_statuses = {
                OnlyVirtualFillPlanStatus.ACTIVE: {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PARTIALLY_FILLED},
                OnlyVirtualFillPlanStatus.COMPLETED: {OnlyOrderStatus.FILLED},
                OnlyVirtualFillPlanStatus.CANCELLED: {OnlyOrderStatus.CANCELLED},
                OnlyVirtualFillPlanStatus.EXPIRED: {OnlyOrderStatus.EXPIRED},
            }
            if order.status not in expected_statuses[plan.status]:
                raise ValueError("VIRTUAL_BROKER_CHECKPOINT_AUTHORITY_CONFLICT")
            order_trades = trades_by_order.get(plan.order_id, [])
            if len(order_trades) != plan.next_step_index:
                raise ValueError("VIRTUAL_BROKER_CHECKPOINT_AUTHORITY_CONFLICT")
            if any(
                trade.fill.quantity != step.quantity
                for trade, step in zip(order_trades, plan.steps[: plan.next_step_index], strict=True)
            ):
                raise ValueError("VIRTUAL_BROKER_CHECKPOINT_AUTHORITY_CONFLICT")
        planned_statuses = {
            OnlyOrderStatus.ACCEPTED,
            OnlyOrderStatus.PARTIALLY_FILLED,
            OnlyOrderStatus.FILLED,
            OnlyOrderStatus.CANCELLED,
            OnlyOrderStatus.EXPIRED,
        }
        if any(
            order.status in planned_statuses and self.fill_plan_store.get(order.order_id) is None
            for order in orders.values()
        ):
            raise ValueError("VIRTUAL_BROKER_CHECKPOINT_AUTHORITY_CONFLICT")
        trades_by_id = {trade.trade_id: trade for trade in trades}
        for raw in self.scheduler.pending_payloads:
            if not isinstance(raw, dict):
                raise ValueError("VIRTUAL_BROKER_SCHEDULED_ACTION_INVALID")
            action_type = raw.get("type")
            if action_type == "SUBMISSION":
                if set(raw) != {
                    "causation_id",
                    "control",
                    "order_id",
                    "submission_index",
                    "type",
                }:
                    raise ValueError("VIRTUAL_BROKER_SCHEDULED_SUBMISSION_AUTHORITY_CONFLICT")
                raw_index = raw.get("submission_index")
                if not isinstance(raw_index, int) or isinstance(raw_index, bool):
                    raise ValueError("VIRTUAL_SUBMISSION_INDEX_INVALID")
                order_id = OnlyOrderId(str(raw.get("order_id")))
                order = orders.get(order_id)
                control = only_virtual_submission_control_from_checkpoint(raw.get("control"))
                expected_control = self.config.submission_simulation.control_for(raw_index)
                if (
                    order is None
                    or order.status is not OnlyOrderStatus.SUBMITTED
                    or not isinstance(raw.get("causation_id"), str)
                    or not raw.get("causation_id")
                    or raw_index > self._venue_order_sequence
                    or str(order.venue_order_id) != f"virtual-order-{raw_index:08d}"
                    or self.fill_plan_store.get(order_id) is not None
                    or trades_by_order.get(order_id)
                    or only_virtual_submission_control_to_checkpoint(expected_control) != raw.get("control")
                    or only_virtual_submission_control_to_checkpoint(control) != raw.get("control")
                ):
                    raise ValueError("VIRTUAL_BROKER_SCHEDULED_SUBMISSION_AUTHORITY_CONFLICT")
                continue
            if action_type == "CANCEL":
                order = orders.get(OnlyOrderId(str(raw.get("order_id"))))
                if order is None:
                    raise ValueError("VIRTUAL_BROKER_SCHEDULED_CANCEL_AUTHORITY_CONFLICT")
                continue
            if action_type != "PUBLISH_FILL":
                raise ValueError("VIRTUAL_BROKER_SCHEDULED_ACTION_INVALID")
            fill = OnlyOrderFill.from_json(str(raw["fill"]))
            plan = self.fill_plan_store.require(OnlyOrderId(str(raw["order_id"])))
            step_index = int(raw["plan_step_index"])
            pending_trade = trades_by_id.get(fill.trade_id)
            if (
                raw.get("plan_id") != plan.plan_id
                or not 1 <= step_index <= plan.next_step_index
                or pending_trade is None
                or pending_trade.fill != fill
                or int(raw["sequence"]) > self._source_sequence
            ):
                raise ValueError("VIRTUAL_BROKER_SCHEDULED_FILL_AUTHORITY_CONFLICT")
        sequence_heads = [
            *(item.source_sequence for item in orders.values()),
            *(item.source_sequence for item in trades),
        ]
        if sequence_heads and max(sequence_heads) > self._source_sequence:
            raise ValueError("VIRTUAL_BROKER_CHECKPOINT_AUTHORITY_CONFLICT")

    def _resolve_scheduled_action(self, payload: object) -> Callable[[], None]:
        if not isinstance(payload, dict):
            raise ValueError("Virtual Broker scheduled action payload must be an object")
        action_type = str(payload["type"])
        order_id = OnlyOrderId(str(payload["order_id"]))
        if action_type == "SUBMISSION":
            if set(payload) != {
                "causation_id",
                "control",
                "order_id",
                "submission_index",
                "type",
            }:
                raise ValueError("VIRTUAL_BROKER_SCHEDULED_SUBMISSION_CONTROL_CONFLICT")
            raw_index = payload.get("submission_index")
            if not isinstance(raw_index, int) or isinstance(raw_index, bool):
                raise ValueError("VIRTUAL_SUBMISSION_INDEX_INVALID")
            causation_id = payload.get("causation_id")
            if not isinstance(causation_id, str) or not causation_id:
                raise ValueError("VIRTUAL_BROKER_SCHEDULED_SUBMISSION_CONTROL_CONFLICT")
            control = only_virtual_submission_control_from_checkpoint(payload.get("control"))
            expected_control = self.config.submission_simulation.control_for(raw_index)
            if only_virtual_submission_control_to_checkpoint(control) != only_virtual_submission_control_to_checkpoint(
                expected_control
            ):
                raise ValueError("VIRTUAL_BROKER_SCHEDULED_SUBMISSION_CONTROL_CONFLICT")
            return lambda: self._apply_submission_control(
                self.order_store.require(order_id),
                causation_id,
                control,
            )
        if action_type == "CANCEL":
            return lambda: self._cancel(order_id, str(payload["causation_id"]))
        if action_type == "PUBLISH_FILL":
            fill = OnlyOrderFill.from_json(str(payload["fill"]))
            timestamp = OnlyTimestamp.from_unix_nanos(int(payload["timestamp_ns"]))
            sequence = int(payload["sequence"])
            return lambda: self._emit(
                OnlyBrokerTradeUpdate,
                timestamp,
                str(order_id),
                str(order_id),
                emitted_sequence=sequence,
                order_id=order_id,
                fill=fill,
            )
        raise ValueError(f"unsupported Virtual Broker scheduled action: {action_type}")

    def _emit(
        self,
        update_type: type[OnlyBrokerInboundUpdate],
        timestamp: OnlyTimestamp,
        correlation_id: str,
        causation_id: str,
        emitted_sequence: int | None = None,
        **payload: object,
    ) -> None:
        sequence = self._next_sequence() if emitted_sequence is None else emitted_sequence
        update = update_type(
            runtime_id=self.runtime_id,
            gateway_id=self.config.gateway_id,
            account_id=self.config.account_id,
            update_id=OnlyBrokerUpdateId(f"virtual-update-{sequence:08d}"),
            source_sequence=sequence,
            ts_event=timestamp,
            ts_init=timestamp,
            correlation_id=correlation_id,
            causation_id=causation_id,
            **payload,  # type: ignore[arg-type]
        )
        self._inbound(update)

    def _next_sequence(self) -> int:
        self._source_sequence += 1
        return self._source_sequence

    def _now(self) -> OnlyTimestamp:
        return OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns())

    def _require_account(self, account_id: OnlyAccountId) -> None:
        if account_id != self.config.account_id:
            raise KeyError(f"unknown Broker account: {account_id}")
