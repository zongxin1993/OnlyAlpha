"""Read-only backtest fact collection from stable Runtime query boundaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum

from onlyalpha.cluster.base import OnlyCluster
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.execution.committed import OnlyCommittedExecutionFact
from onlyalpha.fee.facts import OnlyCommittedFeeReconciliationFact
from onlyalpha.market.runtime_rules import OnlyMarketOrderDecision
from onlyalpha.result.diagnostics import (
    OnlyBacktestDiagnostics,
)
from onlyalpha.result.records import (
    OnlyAccountResultRecord,
    OnlyBacktestFacts,
    OnlyCompiledMarketRuleResultRecord,
    OnlyEquityResultRecord,
    OnlyExecutionResultRecord,
    OnlyExternalFeeEvidenceResultRecord,
    OnlyFeeAdjustmentResultRecord,
    OnlyFeeReconciliationResultRecord,
    OnlyFeeResultRecord,
    OnlyMarginResultRecord,
    OnlyMarketRuleDecisionResultRecord,
    OnlyOrderRequestResultRecord,
    OnlyOrderResultRecord,
    OnlyPositionResultRecord,
    OnlyProfileTimelineResultRecord,
    OnlyRuntimeTransactionResultRecord,
    OnlySequencedResultRecord,
    OnlySettlementInstructionResultRecord,
    OnlySettlementMaturityResultRecord,
    OnlySettlementResultRecord,
    OnlyUnallocatedExternalFeeResultRecord,
)
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.settlement.facts import OnlyCommittedSettlementMaturityFact
from onlyalpha.transaction.projection import OnlyUnallocatedExternalFeeProjection


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
        sequence = 0

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
                (
                    transaction.fact
                    for transaction in runtime.ready_execution_query.ready_records(
                        OnlyRuntimeId(str(runtime.config.runtime_id))
                    )
                    if isinstance(transaction.fact, OnlyCommittedExecutionFact)
                ),
                key=lambda item: item.stable_order,
            )
        )
        executions = tuple(self._execution_record(next_sequence(), item) for item in trades)
        accounts = tuple(sorted(runtime.account_manager.list_accounts(), key=lambda item: str(item.account_id)))
        valuation_times = tuple(
            item.valuation_time.to_datetime() for item in accounts if item.valuation_time is not None
        )
        now = max(valuation_times, default=runtime.clock.now_utc())
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
        for account in accounts:
            account_records.append(
                OnlyAccountResultRecord(
                    sequence=next_sequence(),
                    ts_event=now,
                    trading_day=trading_day,
                    runtime_id=str(account.runtime_id),
                    account_id=str(account.account_id),
                    currency=str(account.base_currency),
                    cash=account.cash.ledger_cash.amount,
                    order_reserved_cash=account.cash.order_reserved_cash.amount,
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
                product = rule_engine.market_product_identity
                compiled_records.append(
                    OnlyCompiledMarketRuleResultRecord(
                        sequence=next_sequence(),
                        instrument_id=str(identity.instrument_id),
                        venue_id=str(identity.instrument_id.venue),
                        trading_day=identity.trading_day.value,
                        profile_id=str(product.product_id),
                        profile_version=str(product.product_version),
                        compiled_rules_fingerprint=identity.policy_fingerprint,
                        reference_fingerprint=identity.reference_fingerprint,
                        runtime_mode=runtime.runtime_type,
                    )
                )
                timeline_records.append(
                    OnlyProfileTimelineResultRecord(
                        sequence=next_sequence(),
                        runtime_id=str(runtime.runtime_id),
                        profile_id=str(product.product_id),
                        profile_version=str(product.product_version),
                        trading_day=identity.trading_day.value,
                        effective_from=None,
                        effective_to=None,
                        resolved_rules_fingerprint=rule_engine.market_composition_fingerprint,
                        reference_fingerprint=identity.reference_fingerprint,
                        override_fingerprint=hashlib.sha256(b"{}").hexdigest(),
                        runtime_mode=runtime.runtime_type,
                    )
                )
            default_account = "" if not account_records else account_records[0].account_id
            for decision in rule_engine.decisions:
                accepted = getattr(decision, "accepted", getattr(decision, "matched", False))
                reason = getattr(decision, "reason_code", getattr(decision, "unfilled_reason", None))
                decision_trading_day: date | None
                if isinstance(decision, OnlyMarketOrderDecision):
                    evaluation_payload = [
                        {
                            "inputs": [list(pair) for pair in item.inputs],
                            "reason_code": item.reason_code,
                            "rule_code": item.rule_code,
                            "status": item.status.value,
                        }
                        for item in decision.evaluations
                    ]
                    ts_event = decision.timestamp
                    decision_trading_day = decision.trading_day.value
                    side = decision.side.value
                    quantity = decision.normalized_quantity
                    price = decision.normalized_price
                    trading_phase = decision.trading_phase.value
                    previous_close = decision.previous_close
                    tick_size = decision.tick_size
                    limit_rate = decision.daily_limit_rate
                    lower_limit = decision.lower_limit
                    upper_limit = decision.upper_limit
                    quantity_policy = json.dumps(
                        {
                            "buy_quantity_increment": str(decision.buy_quantity_increment),
                            "minimum_buy_quantity": str(decision.minimum_buy_quantity),
                            "sell_quantity_increment": str(decision.sell_quantity_increment),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                else:
                    evaluation_payload = []
                    ts_event = now
                    decision_trading_day = None
                    side = None
                    quantity = None
                    price = None
                    trading_phase = None
                    previous_close = None
                    tick_size = None
                    limit_rate = None
                    lower_limit = None
                    upper_limit = None
                    quantity_policy = None
                decision_records.append(
                    OnlyMarketRuleDecisionResultRecord(
                        sequence=next_sequence(),
                        account_id=default_account,
                        instrument_id=str(decision.compiled_identity.instrument_id),
                        market_profile_id=str(rule_engine.market_product_identity.product_id),
                        rule_set_id=decision.compiled_identity.policy_fingerprint,
                        rule_type=type(decision).__name__,
                        decision="ACCEPTED" if accepted else "REJECTED",
                        reason=reason,
                        ts_event=ts_event,
                        trading_day=decision_trading_day,
                        profile_version=str(rule_engine.market_product_identity.product_version),
                        side=side,
                        quantity=quantity,
                        price=price,
                        trading_phase=trading_phase,
                        previous_close=previous_close,
                        tick_size=tick_size,
                        limit_rate=limit_rate,
                        lower_limit=lower_limit,
                        upper_limit=upper_limit,
                        quantity_policy=quantity_policy,
                        reference_fingerprint=decision.compiled_identity.reference_fingerprint,
                        evaluations=json.dumps(evaluation_payload, sort_keys=True, separators=(",", ":")),
                    )
                )
            if not decision_records:
                for fact in trades:
                    decision_records.append(
                        OnlyMarketRuleDecisionResultRecord(
                            sequence=next_sequence(),
                            account_id=str(fact.account_id),
                            instrument_id=str(fact.instrument_id),
                            market_profile_id=fact.market_profile_id,
                            rule_set_id=fact.compiled_rule_fingerprint,
                            rule_type="OnlyMarketOrderDecision",
                            decision="ACCEPTED",
                            reason=None,
                            ts_event=fact.ts_event.to_datetime(),
                        )
                    )
        trade_time_by_id = {str(item.trade_id): item.ts_event.to_datetime() for item in trades}
        settlement_records = tuple(
            OnlySettlementResultRecord(
                sequence=next_sequence(),
                account_id=str(item.instruction.account_id),
                instrument_id=str(item.instruction.instrument_id),
                execution_id=str(item.instruction.trade_id),
                asset_quantity=item.instruction.trade_quantity.value,
                cash_amount=item.instruction.cash_leg.legal_amount.amount,
                trade_time=trade_time_by_id.get(str(item.instruction.trade_id), now),
                asset_available_time=datetime.combine(
                    item.instruction.schedule.asset_trade_available_on.value, time(), UTC
                ),
                cash_available_time=datetime.combine(
                    item.instruction.schedule.cash_trade_available_on.value, time(), UTC
                ),
                settlement_time=datetime.combine(item.instruction.schedule.legal_settlement_on.value, time(), UTC),
                status=item.status.value,
                settlement_model_id=item.instruction.schedule.policy_id,
            )
            for item in runtime.settlement_authority.records
        )
        settlement_instruction_records = tuple(
            OnlySettlementInstructionResultRecord(
                sequence=next_sequence(),
                instruction_id=str(item.instruction.instruction_id),
                runtime_id=str(item.instruction.runtime_id),
                account_id=str(item.instruction.account_id),
                cluster_id=str(item.instruction.cluster_id),
                instrument_id=str(item.instruction.instrument_id),
                order_id=str(item.instruction.order_id),
                trade_id=str(item.instruction.trade_id),
                position_id=str(item.instruction.position_id),
                position_cycle=item.instruction.position_cycle,
                allocation_id=str(item.instruction.allocation_id),
                allocation_cycle=item.instruction.allocation_cycle,
                side=item.instruction.side.value,
                quantity=item.instruction.trade_quantity.value,
                gross_notional=item.instruction.gross_notional.amount,
                net_cash_flow=item.instruction.net_cash_flow.amount,
                trading_day=item.instruction.trading_day.value,
                asset_trade_available_on=item.instruction.schedule.asset_trade_available_on.value,
                cash_trade_available_on=item.instruction.schedule.cash_trade_available_on.value,
                cash_withdrawable_on=item.instruction.schedule.cash_withdrawable_on.value,
                legal_settlement_on=item.instruction.schedule.legal_settlement_on.value,
                policy_id=item.instruction.schedule.policy_id,
                compiled_rule_fingerprint=item.instruction.compiled_rule_fingerprint,
                reference_fingerprint=item.instruction.reference_fingerprint,
                status=item.status.value,
                version=item.version,
            )
            for item in runtime.settlement_authority.snapshots()
        )
        transactions = runtime.ready_execution_query.ready_records(OnlyRuntimeId(str(runtime.config.runtime_id)))
        settlement_maturity_records = tuple(
            OnlySettlementMaturityResultRecord(
                sequence=next_sequence(),
                maturity_identity=item.fact.maturity_identity,
                instruction_id=str(item.fact.instruction_id),
                runtime_id=str(item.runtime_id),
                account_id=str(item.fact.account_id),
                effective_on=item.fact.effective_on.value,
                transitions_json=json.dumps(
                    [transition.value for transition in item.fact.transitions], separators=(",", ":")
                ),
                asset_quantity_delta=item.fact.asset_available_delta.value,
                cash_withdrawable_delta=item.fact.cash_withdrawable_delta.amount,
                runtime_sequence=item.execution_sequence,
                transaction_id=item.transaction_id,
                projection_ready=item.projection_ready,
            )
            for item in transactions
            if isinstance(item.fact, OnlyCommittedSettlementMaturityFact)
        )
        runtime_transaction_records = tuple(
            OnlyRuntimeTransactionResultRecord(
                sequence=next_sequence(),
                runtime_sequence=item.execution_sequence,
                transaction_id=item.transaction_id,
                operation_kind=item.operation_kind.value,
                operation_identity=item.operation_identity,
                runtime_id=str(item.runtime_id),
                account_id=None if item.account_id is None else str(item.account_id),
                effective_time=item.effective_time.to_datetime(),
                projection_ready=item.projection_ready,
            )
            for item in transactions
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
                fee_record_id=item.record_id,
                instruction_id=item.application_id,
                idempotency_key=item.application_id,
                account_id=str(item.account_id),
                instrument_id=str(item.instrument_id),
                order_id=str(item.order_id),
                trade_id=str(item.trade_id),
                fee_type=item.component_identity.fee_type.value,
                authority=item.component_identity.authority.value,
                status=item.local_finality.value,
                accrued=item.cumulative_target_after.amount,
                charged=item.incremental_amount.amount,
                currency=item.incremental_amount.currency.code,
                schedule_id=item.component_identity.schedule_id,
                schedule_version=item.component_identity.schedule_version,
            )
            for item in runtime.fee_application_ledger.records
        )
        reconciliation_transactions = tuple(
            (item, item.fact) for item in transactions if isinstance(item.fact, OnlyCommittedFeeReconciliationFact)
        )
        external_fee_evidence = tuple(
            OnlyExternalFeeEvidenceResultRecord(
                sequence=next_sequence(),
                evidence_id=fact.evidence.evidence_id,
                broker_id=fact.evidence.broker_id,
                account_id=str(fact.evidence.account_id),
                scope=fact.evidence.scope.scope_type.value,
                mode=fact.evidence.mode.value,
                external_reference=fact.evidence.external_reference,
                report_version=fact.evidence.report_version,
                revision_sequence=fact.evidence.revision_sequence,
                supersedes_evidence_id=fact.evidence.supersedes_evidence_id or "",
                scope_fingerprint=fact.evidence.scope.fingerprint,
                content_fingerprint=fact.evidence.content_fingerprint,
                reported_total=None if fact.evidence.reported_total is None else fact.evidence.reported_total.amount,
                currency=(
                    fact.evidence.reported_total.currency.code
                    if fact.evidence.reported_total is not None
                    else fact.evidence.reported_components[0].amount.currency.code
                ),
                effective_at=fact.evidence.effective_at.to_datetime(),
                received_at=fact.evidence.received_at.to_datetime(),
            )
            for _, fact in reconciliation_transactions
        )
        fee_reconciliations = tuple(
            OnlyFeeReconciliationResultRecord(
                sequence=next_sequence(),
                reconciliation_id=fact.decision.reconciliation_id,
                evidence_id=fact.decision.evidence_id,
                evidence_family_fingerprint=fact.decision.evidence_family_fingerprint,
                scope=fact.evidence.scope.scope_type.value,
                local_model_amount=fact.decision.aggregate_local.amount,
                prior_adjustments=fact.decision.aggregate_prior_adjustment.amount,
                current_effective_amount=(
                    fact.decision.aggregate_local.amount + fact.decision.aggregate_prior_adjustment.amount
                ),
                reported_authoritative_amount=fact.decision.aggregate_reported.amount,
                difference=fact.decision.aggregate_difference.amount,
                currency=fact.decision.aggregate_difference.currency.code,
                reason="" if fact.decision.reason is None else fact.decision.reason.value,
                status=fact.decision.status.value,
                adjustment_id=",".join(item.adjustment_id for item in fact.decision.adjustments),
                policy_id=fact.decision.policy_identity.policy_id,
                policy_version=fact.decision.policy_identity.policy_version,
                policy_fingerprint=fact.decision.policy_identity.fingerprint,
                local_facts_fingerprint=fact.decision.local_facts_fingerprint,
                prior_adjustments_fingerprint=fact.decision.prior_adjustments_fingerprint,
                component_rows_json=json.dumps(
                    [item.to_dict() for item in fact.decision.component_reconciliations],
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                resolves_blocker_id=fact.decision.resolves_blocker_id or "",
            )
            for _, fact in reconciliation_transactions
        )
        fee_adjustments = tuple(
            OnlyFeeAdjustmentResultRecord(
                sequence=next_sequence(),
                adjustment_id=adjustment.adjustment_id,
                reconciliation_id=adjustment.reconciliation_id,
                evidence_id=adjustment.evidence_id,
                account_id=str(adjustment.account_id),
                cluster_id="" if adjustment.cluster_id is None else str(adjustment.cluster_id),
                direction=adjustment.direction.value,
                amount=adjustment.amount.amount,
                currency=adjustment.amount.currency.code,
                reason=adjustment.reason.value,
                component_id=adjustment.component_identity.normalized_component_id,
                component_fee_type=adjustment.component_identity.fee_type.value,
                component_authority=adjustment.component_identity.authority.value,
                policy_fingerprint=adjustment.policy_identity.fingerprint,
            )
            for _, fact in reconciliation_transactions
            for adjustment in fact.decision.adjustments
        )
        unallocated_external_fees = tuple(
            OnlyUnallocatedExternalFeeResultRecord(
                sequence=next_sequence(),
                account_id=str(projection.after.account_id),
                cumulative_charges=projection.after.cumulative_charges.amount,
                cumulative_refunds=projection.after.cumulative_refunds.amount,
                currency=projection.after.cumulative_charges.currency.code,
                version=projection.after.version,
            )
            for item, _ in reconciliation_transactions
            for projection in item.projections
            if isinstance(projection, OnlyUnallocatedExternalFeeProjection)
        )
        failures = list(runtime.result_progress.snapshot().business_failures)
        diagnostics = OnlyBacktestDiagnostics(
            tuple(failures),
            (),
            False,
            len(failures),
            runtime.execution_recovery_diagnostics,
        )
        facts = OnlyBacktestFacts(
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
            settlement_instructions=settlement_instruction_records,
            settlement_maturities=settlement_maturity_records,
            runtime_transactions=runtime_transaction_records,
            margin=margin_records,
            fees=fee_records,
            external_fee_evidence=external_fee_evidence,
            fee_reconciliations=fee_reconciliations,
            fee_adjustments=fee_adjustments,
            unallocated_external_fees=unallocated_external_fees,
        )
        fact_sequence = 0

        def normalize[T: OnlySequencedResultRecord](records: tuple[T, ...]) -> tuple[T, ...]:
            nonlocal fact_sequence
            normalized: list[T] = []
            for record in records:
                fact_sequence += 1
                normalized.append(replace(record, sequence=fact_sequence))
            return tuple(normalized)

        facts = OnlyBacktestFacts(
            signals=normalize(facts.signals),
            order_requests=normalize(facts.order_requests),
            orders=normalize(facts.orders),
            executions=normalize(facts.executions),
            positions=normalize(facts.positions),
            accounts=normalize(facts.accounts),
            equity=normalize(facts.equity),
            settlements=normalize(facts.settlements),
            settlement_instructions=normalize(facts.settlement_instructions),
            settlement_maturities=normalize(facts.settlement_maturities),
            runtime_transactions=normalize(facts.runtime_transactions),
            margin=normalize(facts.margin),
            fees=normalize(facts.fees),
            external_fee_evidence=normalize(facts.external_fee_evidence),
            fee_reconciliations=normalize(facts.fee_reconciliations),
            fee_adjustments=normalize(facts.fee_adjustments),
            unallocated_external_fees=normalize(facts.unallocated_external_fees),
            market_rule_decisions=normalize(facts.market_rule_decisions),
            profile_timeline=normalize(facts.profile_timeline),
            compiled_market_rules=normalize(facts.compiled_market_rules),
        )
        self._collected = OnlyCollectedBacktestFacts(
            facts,
            diagnostics,
            fact_sequence,
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
        for component in trade.fee_application.components:
            key = component.identity.fee_type.value
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
            fees=trade.fee_total_charges.amount - trade.fee_total_rebates.amount,
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
            fee_application_id=trade.fee_application_id,
            market_fee_pack_id=trade.market_fee_pack_id,
            market_fee_pack_version=trade.market_fee_pack_version,
            market_fee_pack_fingerprint=trade.market_fee_pack_fingerprint,
            broker_fee_contract_id=trade.broker_fee_contract_id,
            broker_fee_contract_version=trade.broker_fee_contract_version,
            broker_fee_contract_broker_id=trade.broker_fee_contract_broker_id,
            broker_fee_contract_account_scope=trade.broker_fee_contract_account_scope,
            broker_fee_contract_fingerprint=trade.broker_fee_contract_fingerprint,
            fee_binding_fingerprint=trade.fee_binding_fingerprint,
            fee_scope_fingerprint=trade.fee_scope_fingerprint,
            fee_resolution_fingerprint=trade.fee_resolution_fingerprint,
            fee_total_charges=trade.fee_total_charges.amount,
            fee_total_rebates=trade.fee_total_rebates.amount,
            fee_signed_cash_effect=trade.fee_signed_cash_effect,
            market_fee_schedule_ids=trade.market_fee_schedule_ids,
            market_fee_schedule_versions=trade.market_fee_schedule_versions,
            market_fee_schedule_fingerprints=trade.market_fee_schedule_fingerprints,
            broker_fee_schedule_ids=trade.broker_fee_schedule_ids,
            broker_fee_schedule_versions=trade.broker_fee_schedule_versions,
            broker_fee_schedule_fingerprints=trade.broker_fee_schedule_fingerprints,
            settlement_instruction_id=trade.settlement_instruction_id,
            settlement_status=trade.settlement_status,
            margin_instruction_id=trade.margin_instruction_id,
            margin_action=trade.margin_action,
            margin_amount=None if trade.margin_amount is None else trade.margin_amount.amount,
            liquidity_side=trade.liquidity_side.value,
            fee_breakdown=fee_breakdown,
            liquidity={
                "side": trade.liquidity_side.value,
                "fee_application_id": trade.fee_application_id,
            },
        )
