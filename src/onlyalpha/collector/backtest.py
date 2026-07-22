"""Read-only backtest fact collection from stable Runtime query boundaries."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from decimal import Decimal
from enum import StrEnum

from onlyalpha.cluster.base import OnlyCluster
from onlyalpha.data.enums import OnlyMarketDataProcessingStatus
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.execution.committed import OnlyCommittedExecutionFact
from onlyalpha.market_data.dispatcher import OnlyBarDispatchResult
from onlyalpha.result.diagnostics import (
    OnlyBacktestDiagnostics,
    OnlyBacktestFailure,
    OnlyResultDiagnosticSeverity,
    OnlyResultFailureStage,
)
from onlyalpha.result.records import (
    OnlyAccountResultRecord,
    OnlyBacktestFacts,
    OnlyCompiledMarketRuleResultRecord,
    OnlyEquityResultRecord,
    OnlyExecutionResultRecord,
    OnlyFeeResultRecord,
    OnlyMarginResultRecord,
    OnlyMarketRuleDecisionResultRecord,
    OnlyOrderRequestResultRecord,
    OnlyOrderResultRecord,
    OnlyPositionResultRecord,
    OnlyProfileTimelineResultRecord,
    OnlySettlementResultRecord,
)
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime


class OnlyResultCollectorLifecycle(StrEnum):
    CREATED = "CREATED"
    STARTED = "STARTED"
    SEALED = "SEALED"


class OnlyResultCollectorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OnlyCollectedBacktestFacts:
    facts: OnlyBacktestFacts
    diagnostics: OnlyBacktestDiagnostics
    last_sequence: int


class OnlyBacktestResultCollector:
    """Build immutable facts without mutating or driving Runtime state."""

    def __init__(self) -> None:
        self._lifecycle = OnlyResultCollectorLifecycle.CREATED
        self._collected: OnlyCollectedBacktestFacts | None = None

    @property
    def lifecycle(self) -> OnlyResultCollectorLifecycle:
        return self._lifecycle

    def start(self) -> None:
        if self._lifecycle is not OnlyResultCollectorLifecycle.CREATED:
            raise OnlyResultCollectorError("collector can start only once")
        self._lifecycle = OnlyResultCollectorLifecycle.STARTED

    def seal(
        self,
        runtime: OnlyBacktestRuntime,
        clusters: tuple[OnlyCluster, ...],
    ) -> OnlyCollectedBacktestFacts:
        if self._lifecycle is not OnlyResultCollectorLifecycle.STARTED:
            raise OnlyResultCollectorError("collector must be started before seal")
        sequence = max((int(item.event.sequence) for item in runtime.event_bus.dispatch_results), default=0)

        def next_sequence() -> int:
            nonlocal sequence
            sequence += 1
            return sequence

        cluster_strategy = {cluster.config.cluster_id: str(cluster.strategy.strategy_id) for cluster in clusters}
        local_signals = tuple(
            signal
            for cluster in sorted(clusters, key=lambda item: item.config.cluster_id)
            for signal in cluster.strategy.context.results.seal()
        )
        signals = tuple(replace(signal, sequence=next_sequence()) for signal in local_signals)
        orders = tuple(sorted(runtime.order_manager.snapshot_all(), key=lambda item: str(item.order_id)))
        request_records = tuple(self._request_record(next_sequence(), item, cluster_strategy) for item in orders)
        order_records = tuple(self._order_record(next_sequence(), item, cluster_strategy) for item in orders)
        trades = tuple(
            sorted(
                runtime.committed_execution_journal.records(),
                key=lambda item: item.stable_order,
            )
        )
        executions = tuple(self._execution_record(next_sequence(), item) for item in trades)
        now = runtime.clock.now_utc()
        trading_day = now.date()
        positions = tuple(
            OnlyPositionResultRecord(
                sequence=next_sequence(),
                ts_event=now,
                trading_day=trading_day,
                runtime_id=str(item.key.runtime_id),
                cluster_id=None,
                strategy_id=None,
                account_id=str(item.key.account_id),
                instrument_id=str(item.key.instrument_id),
                total_quantity=item.total_quantity.value,
                available_quantity=item.available_quantity.value,
                frozen_quantity=item.frozen_quantity.value,
                average_price=None if item.average_open_price is None else item.average_open_price.value,
                mark_price=None,
                market_value=None,
                realized_pnl=item.realized_pnl.amount,
                unrealized_pnl=None,
                position_side=item.position_side.value,
            )
            for item in sorted(runtime.position_manager.snapshot_all(), key=lambda value: str(value.position_id))
        )
        account_records: list[OnlyAccountResultRecord] = []
        equity_records: list[OnlyEquityResultRecord] = []
        for account in sorted(runtime.account_manager.list_accounts(), key=lambda item: str(item.account_id)):
            account_records.append(
                OnlyAccountResultRecord(
                    sequence=next_sequence(),
                    ts_event=now,
                    trading_day=trading_day,
                    runtime_id=str(account.runtime_id),
                    account_id=str(account.account_id),
                    currency=str(account.base_currency),
                    cash=account.cash.cash_balance.amount,
                    frozen_cash=account.cash.frozen_cash.amount,
                    market_value=account.position_market_value.amount,
                    equity=account.equity.amount,
                    realized_pnl=account.realized_pnl.amount,
                    unrealized_pnl=account.unrealized_pnl.amount,
                    commission=Decimal(0),
                    fees=account.fees.amount,
                    reserved_margin=Decimal(0) if account.reserved_margin is None else account.reserved_margin.amount,
                    occupied_margin=Decimal(0) if account.occupied_margin is None else account.occupied_margin.amount,
                    released_margin=Decimal(0) if account.released_margin is None else account.released_margin.amount,
                    available_margin=Decimal(0)
                    if account.available_margin is None
                    else account.available_margin.amount,
                )
            )
            equity_records.extend(
                OnlyEquityResultRecord(
                    sequence=next_sequence(),
                    ts_event=point.ts_event.to_datetime(),
                    trading_day=(
                        point.ts_event.to_datetime().date() if point.trading_day is None else point.trading_day.value
                    ),
                    runtime_id=str(point.runtime_id),
                    account_id=str(point.account_id),
                    cluster_id=None,
                    currency=point.currency.code,
                    cash=point.cash.amount,
                    market_value=point.position_market_value.amount,
                    equity=point.equity.amount,
                    realized_pnl=point.realized_pnl.amount,
                    unrealized_pnl=point.unrealized_pnl.amount,
                    commission=Decimal(0),
                    fees=point.fees.amount,
                    gross_exposure=point.position_market_value.amount,
                    net_exposure=point.position_market_value.amount,
                    position_count=len(runtime.position_manager.list_by_account(account.account_id)),
                    complete=True,
                    snapshot_phase=point.source.value,
                )
                for point in runtime.account_performance_projector.timeline(account.account_id)
            )
        rule_engine = runtime.config.market_rule_engine
        compiled_records: list[OnlyCompiledMarketRuleResultRecord] = []
        timeline_records: list[OnlyProfileTimelineResultRecord] = []
        decision_records: list[OnlyMarketRuleDecisionResultRecord] = []
        if rule_engine is not None:
            for identity in rule_engine.compiled_identities:
                compiled_records.append(
                    OnlyCompiledMarketRuleResultRecord(
                        sequence=next_sequence(),
                        instrument_id=identity.instrument_id,
                        venue_id=identity.venue,
                        trading_day=identity.trading_day,
                        profile_id=identity.profile_id,
                        profile_version=identity.profile_version,
                        compiled_rules_fingerprint=identity.compiled_rules_fingerprint,
                        reference_fingerprint=identity.reference_fingerprint,
                        runtime_mode=identity.runtime_mode.value,
                    )
                )
                timeline_records.append(
                    OnlyProfileTimelineResultRecord(
                        sequence=next_sequence(),
                        runtime_id=str(runtime.runtime_id),
                        profile_id=identity.profile_id,
                        profile_version=identity.profile_version,
                        trading_day=identity.trading_day,
                        effective_from=None,
                        effective_to=None,
                        resolved_rules_fingerprint=identity.resolved_profile_fingerprint,
                        reference_fingerprint=identity.reference_fingerprint,
                        override_fingerprint=hashlib.sha256(b"{}").hexdigest(),
                        runtime_mode=identity.runtime_mode.value,
                    )
                )
            default_account = "" if not account_records else account_records[0].account_id
            for decision in rule_engine.decisions:
                accepted = getattr(decision, "accepted", getattr(decision, "matched", False))
                reason = getattr(decision, "reason_code", getattr(decision, "unfilled_reason", None))
                decision_records.append(
                    OnlyMarketRuleDecisionResultRecord(
                        sequence=next_sequence(),
                        account_id=default_account,
                        instrument_id=decision.compiled_identity.instrument_id,
                        market_profile_id=decision.compiled_identity.profile_id,
                        rule_set_id=decision.compiled_identity.compiled_rules_fingerprint,
                        rule_type=type(decision).__name__,
                        decision="ACCEPTED" if accepted else "REJECTED",
                        reason=reason,
                        ts_event=now,
                    )
                )
        settlement_records = tuple(
            OnlySettlementResultRecord(
                sequence=next_sequence(),
                account_id=item.account_id,
                instrument_id=item.instrument_id,
                execution_id=item.source_trade_id,
                asset_quantity=item.booked_quantity,
                cash_amount=item.cash_amount,
                trade_time=now,
                asset_available_time=datetime.combine(item.processed_on.value, time(), UTC),
                cash_available_time=datetime.combine(item.processed_on.value, time(), UTC),
                settlement_time=datetime.combine(
                    (item.legal_settlement_date or item.processed_on).value,
                    time(),
                    UTC,
                ),
                status=item.status,
                settlement_model_id="MARKET_RULE_INSTRUCTION",
            )
            for item in runtime.settlement_manager.records
        )
        margin_records = tuple(
            OnlyMarginResultRecord(
                sequence=next_sequence(),
                account_id=item.account_id,
                instrument_id=item.instrument_id,
                position_side="",
                initial_margin=item.reserved_after + item.occupied_after,
                maintenance_margin=item.maintenance_required_after,
                used_margin=item.occupied_after,
                available_margin=Decimal(0),
                margin_ratio=None,
                margin_record_id=f"MARGIN-{item.sequence:08d}",
                order_id=item.source_order_id,
                trade_id=item.source_trade_id,
                operation=item.action,
                reserved_delta=item.amount
                if item.action == "RESERVE"
                else -item.amount
                if item.action == "OCCUPY"
                else Decimal(0),
                occupied_delta=item.amount
                if item.action == "OCCUPY"
                else -item.amount
                if item.action == "RELEASE"
                else Decimal(0),
                released_delta=item.amount if item.action == "RELEASE" else Decimal(0),
                currency=item.currency,
                amount=item.amount,
            )
            for item in runtime.margin_manager.records
        )
        fee_records = tuple(
            OnlyFeeResultRecord(
                sequence=next_sequence(),
                fee_record_id=item.fee_record_id,
                instruction_id=item.instruction_id,
                idempotency_key=item.idempotency_key,
                account_id=item.account_id,
                instrument_id=item.instrument_id,
                order_id=item.order_id,
                trade_id=item.trade_id,
                fee_type=item.fee_type,
                authority=item.authority,
                status=item.status,
                accrued=item.accrued,
                charged=item.charged,
                currency=item.currency,
                schedule_id=item.schedule_id,
                schedule_version=item.schedule_version,
            )
            for item in runtime.fee_manager.records
        )
        failures: list[OnlyBacktestFailure] = []
        for audit in runtime.market_data_audit_store.records():
            if audit.failure is None and audit.status is not OnlyMarketDataProcessingStatus.REJECTED:
                continue
            sequence += 1
            if audit.failure is None:
                exception_type = "OnlyMarketDataValidationError"
                message = "; ".join(audit.validation_reasons) or "market data rejected"
            else:
                exception_type, separator, message = audit.failure.partition(": ")
                if not separator:
                    exception_type, message = "OnlyMarketDataProcessingError", audit.failure
            stable_identity = (
                f"{audit.runtime_id}:{audit.processing_sequence}:{audit.update_id}:{exception_type}:{message}"
            )
            failures.append(
                OnlyBacktestFailure(
                    failure_id=hashlib.sha256(stable_identity.encode("utf-8")).hexdigest(),
                    sequence=sequence,
                    severity=OnlyResultDiagnosticSeverity.ERROR,
                    stage=OnlyResultFailureStage.MARKET_DATA_PIPELINE,
                    exception_type=exception_type,
                    message=message,
                    ts_event=audit.ts_event.to_datetime(),
                    trading_day=audit.ts_event.to_datetime().date(),
                    runtime_id=str(audit.runtime_id),
                    source_id=str(audit.source_id),
                    instrument_id=str(audit.instrument_id),
                )
            )
        for replay_event in runtime.historical_replay_service.events:
            for dispatch in replay_event.result.dispatches:
                if not isinstance(dispatch, OnlyBarDispatchResult):
                    continue
                if dispatch.error_message is None:
                    continue
                sequence += 1
                exception_type, separator, message = dispatch.error_message.partition(": ")
                if not separator:
                    exception_type, message = "OnlyStrategyCallbackError", dispatch.error_message
                update = replay_event.update
                stable_identity = (
                    f"{update.runtime_id}:{dispatch.cluster_id}:{replay_event.index}:{exception_type}:{message}"
                )
                failures.append(
                    OnlyBacktestFailure(
                        failure_id=hashlib.sha256(stable_identity.encode("utf-8")).hexdigest(),
                        sequence=sequence,
                        severity=OnlyResultDiagnosticSeverity.ERROR,
                        stage=OnlyResultFailureStage.STRATEGY,
                        exception_type=exception_type,
                        message=message,
                        ts_event=update.ts_event.to_datetime(),
                        trading_day=update.ts_event.to_datetime().date(),
                        runtime_id=str(update.runtime_id),
                        cluster_id=str(dispatch.cluster_id),
                        source_id=str(update.source_id),
                        instrument_id=str(update.instrument_id),
                        bar_type=None if update.bar_type is None else update.bar_type.to_json(),
                    )
                )
        diagnostics = OnlyBacktestDiagnostics(tuple(failures), (), False, len(failures))
        self._collected = OnlyCollectedBacktestFacts(
            OnlyBacktestFacts(
                signals=tuple(sorted(signals, key=lambda item: item.sequence)),
                order_requests=request_records,
                orders=order_records,
                executions=executions,
                positions=positions,
                accounts=tuple(account_records),
                equity=tuple(equity_records),
                market_rule_decisions=tuple(decision_records),
                profile_timeline=tuple(timeline_records),
                compiled_market_rules=tuple(compiled_records),
                settlements=settlement_records,
                margin=margin_records,
                fees=fee_records,
            ),
            diagnostics,
            sequence,
        )
        self._lifecycle = OnlyResultCollectorLifecycle.SEALED
        return self._collected

    def snapshot(self) -> OnlyCollectedBacktestFacts:
        if self._lifecycle is not OnlyResultCollectorLifecycle.SEALED or self._collected is None:
            raise OnlyResultCollectorError("collector result is unavailable before seal")
        return self._collected

    @staticmethod
    def _request_record(
        sequence: int,
        order: OnlyOrderSnapshot,
        strategy_by_cluster: dict[str, str],
    ) -> OnlyOrderRequestResultRecord:
        return OnlyOrderRequestResultRecord(
            sequence=sequence,
            request_id=str(order.request_id),
            runtime_id=str(order.runtime_id),
            cluster_id=str(order.cluster_id),
            strategy_id=strategy_by_cluster[str(order.cluster_id)],
            account_id=str(order.account_id),
            instrument_id=str(order.instrument_id),
            side=order.side.value,
            offset=order.offset.value,
            order_type=order.order_type.value,
            quantity=order.quantity.value,
            limit_price=None if order.price is None else order.price.value,
            stop_price=None if order.stop_price is None else order.stop_price.value,
            submitted_at=(order.submitted_at or order.created_at).to_datetime(),
            tags=order.tags,
        )

    @staticmethod
    def _order_record(
        sequence: int,
        order: OnlyOrderSnapshot,
        strategy_by_cluster: dict[str, str],
    ) -> OnlyOrderResultRecord:
        completed = next(
            (
                item
                for item in (
                    order.filled_at,
                    order.cancelled_at,
                    order.rejected_at,
                    order.expired_at,
                    order.failed_at,
                )
                if item is not None
            ),
            None,
        )
        return OnlyOrderResultRecord(
            sequence=sequence,
            order_id=str(order.order_id),
            request_id=str(order.request_id),
            runtime_id=str(order.runtime_id),
            cluster_id=str(order.cluster_id),
            strategy_id=strategy_by_cluster[str(order.cluster_id)],
            account_id=str(order.account_id),
            instrument_id=str(order.instrument_id),
            side=order.side.value,
            offset=order.offset.value,
            order_type=order.order_type.value,
            requested_quantity=order.quantity.value,
            filled_quantity=order.filled_quantity.value,
            remaining_quantity=order.remaining_quantity.value,
            status=order.status.value,
            submitted_at=(order.submitted_at or order.created_at).to_datetime(),
            accepted_at=None if order.accepted_at is None else order.accepted_at.to_datetime(),
            completed_at=None if completed is None else completed.to_datetime(),
            rejection_code=None if order.rejection is None else order.rejection.code,
            rejection_message=None if order.rejection is None else order.rejection.message,
            tags=order.tags,
        )

    @staticmethod
    def _execution_record(
        sequence: int,
        trade: OnlyCommittedExecutionFact,
    ) -> OnlyExecutionResultRecord:
        fee_breakdown: dict[str, Decimal] = {}
        for component in trade.fee_breakdown.components:
            key = component.fee_type.value
            fee_breakdown[key] = fee_breakdown.get(key, Decimal(0)) + component.amount.amount
        return OnlyExecutionResultRecord(
            sequence=sequence,
            execution_id=trade.execution_id,
            order_id=str(trade.order_id),
            request_id=trade.request_id,
            runtime_id=str(trade.runtime_id),
            cluster_id=str(trade.cluster_id),
            strategy_id=str(trade.strategy_id),
            account_id=str(trade.account_id),
            instrument_id=str(trade.instrument_id),
            side=trade.order_side.value,
            offset=trade.offset.value,
            quantity=trade.fill_quantity.value,
            price=trade.fill_price.value,
            turnover=trade.gross_notional.amount,
            commission=trade.commission.amount,
            fees=trade.authoritative_fee_total.amount,
            slippage=None if trade.slippage is None else trade.slippage.amount,
            ts_event=trade.ts_event.to_datetime(),
            trading_day=trade.trading_day.value,
            venue=trade.venue_id,
            position_side=trade.position_side.value,
            position_effect=trade.position_effect.value,
            position_mode=trade.position_mode.value,
            realized_pnl_delta=trade.realized_pnl_delta.amount,
            reference_price=None if trade.reference_price is None else trade.reference_price.value,
            contract_multiplier=trade.contract_multiplier.value,
            market_profile_id=trade.market_profile_id,
            market_profile_version=trade.market_profile_version,
            compiled_rule_fingerprint=trade.compiled_rule_fingerprint,
            reference_fingerprint=trade.reference_fingerprint,
            trade_instruction_id=trade.trade_instruction_id,
            fee_instruction_id=trade.fee_instruction_id,
            market_fee_schedule_ids=trade.market_fee_schedule_ids,
            market_fee_schedule_versions=trade.market_fee_schedule_versions,
            broker_fee_schedule_ids=trade.broker_fee_schedule_ids,
            broker_fee_schedule_versions=trade.broker_fee_schedule_versions,
            settlement_instruction_id=trade.settlement_instruction_id,
            settlement_status=trade.settlement_status,
            margin_instruction_id=trade.margin_instruction_id,
            margin_action=trade.margin_action,
            margin_amount=None if trade.margin_amount is None else trade.margin_amount.amount,
            reported_broker_fee=None if trade.reported_broker_fee is None else trade.reported_broker_fee.amount,
            fee_reporting_mode=trade.fee_reporting_mode.value,
            liquidity_side=trade.liquidity_side.value,
            fee_breakdown=fee_breakdown,
            liquidity={
                "side": trade.liquidity_side.value,
                "fee_reporting_mode": trade.fee_reporting_mode.value,
                "reported_broker_fee": (
                    None if trade.reported_broker_fee is None else trade.reported_broker_fee.amount
                ),
            },
        )
