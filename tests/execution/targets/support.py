from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.execution import (
    OnlyAppliedProjectionLedger,
    OnlyCommittedExecutionTransaction,
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionApplyContext,
    OnlyExecutionProjectionBatchResult,
    OnlyExecutionProjectionBatchStatus,
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionTarget,
    OnlyExecutionValuationAuthority,
    OnlyInMemoryAppliedProjectionLedger,
    OnlyProjectionApplyStatus,
    OnlyValuationExecutionState,
    only_create_generic_t0_execution_projection_targets,
)
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore, OnlyRuntimePersistenceStorePort
from tests.execution.support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    only_test_generic_t0_projection_environment,
)
from tests.execution.support.manager_authority_digest import only_test_runtime_authority_digest
from tests.integration_demo.environment import OnlyIntegrationEnvironment


@dataclass(slots=True)
class OnlyTestProjectionTargetBundle:
    environment: OnlyIntegrationEnvironment
    transaction: OnlyCommittedExecutionTransaction
    valuation_authority: OnlyExecutionValuationAuthority
    applied_ledger: OnlyInMemoryAppliedProjectionLedger
    targets: dict[OnlyExecutionProjectionComponent, OnlyExecutionProjectionTarget]
    transaction_store: OnlyRuntimePersistenceStorePort

    def apply_all(self) -> OnlyExecutionProjectionBatchResult:
        return OnlyExecutionProjectionApplier(self.targets).apply(self.transaction)

    def create_targets(
        self, ledger: OnlyAppliedProjectionLedger
    ) -> dict[OnlyExecutionProjectionComponent, OnlyExecutionProjectionTarget]:
        runtime = self.environment.runtime
        return dict(
            only_create_generic_t0_execution_projection_targets(
                order_manager=runtime.order_manager,
                position_manager=runtime.position_manager,
                allocation_manager=runtime.allocation_manager,
                settlement_manager=runtime.settlement_manager,
                fee_manager=runtime.fee_manager,
                order_fee_accrual_manager=runtime.order_fee_accrual_manager,
                account_manager=runtime.account_manager,
                ledger_manager=runtime.strategy_ledger_manager,
                risk_service=runtime.risk_service,
                valuation_authority=self.valuation_authority,
                applied_ledger=ledger,
            )
        )


def only_test_projection_target_bundle(
    scenario: OnlyTestGenericT0Scenario | None = None,
    transaction_store: OnlyRuntimePersistenceStorePort | None = None,
) -> OnlyTestProjectionTargetBundle:
    selected = scenario or OnlyTestGenericT0Scenario("real-target")
    environment, context, prepared = only_test_generic_t0_projection_environment(selected)
    store = transaction_store or OnlyInMemoryRuntimePersistenceStore()
    committed = store.commit(prepared, committed_at=context.prepared_at).transaction
    runtime = environment.runtime

    def current_valuation(account_id: OnlyAccountId) -> OnlyValuationExecutionState | None:
        timeline = runtime.account_performance_projector.timeline(account_id)
        if not timeline:
            return None
        point = timeline[-1]
        return OnlyValuationExecutionState(
            point.account_id,
            point.ts_event,
            point.cash,
            point.position_market_value,
            point.unrealized_pnl,
            point.equity,
            runtime.execution_valuation_version,
        )

    valuation = OnlyExecutionValuationAuthority(
        {context.valuation_before.account_id: context.valuation_before},
        runtime.account_performance_projector,
        lambda state: runtime.restore_execution_valuation_version(state.version),
        current_valuation,
    )
    ledger = OnlyInMemoryAppliedProjectionLedger()
    bundle = OnlyTestProjectionTargetBundle(environment, committed, valuation, ledger, {}, store)
    bundle.targets = bundle.create_targets(ledger)
    return bundle


def only_test_assert_component_applies(component: OnlyExecutionProjectionComponent) -> None:
    bundle = only_test_projection_target_bundle()
    context = only_test_projection_context(bundle, component)
    projection = context.projection
    target = bundle.targets[component]
    first = target.apply_execution_projection(context)
    second = target.apply_execution_projection(context)
    assert first.status is OnlyProjectionApplyStatus.APPLIED
    assert first.after_state_hash == projection.identity.result_state_hash
    assert second.status is OnlyProjectionApplyStatus.IDEMPOTENT
    assert len(bundle.applied_ledger.records()) == 1

    conflict = OnlyExecutionProjectionApplyContext(
        f"{context.transaction_id}-conflict",
        context.execution_sequence,
        context.fact,
        projection,
    )
    before_conflict = only_test_runtime_authority_digest(bundle.environment)
    assert target.apply_execution_projection(conflict).status is OnlyProjectionApplyStatus.PAYLOAD_CONFLICT
    assert only_test_runtime_authority_digest(bundle.environment) == before_conflict

    fresh_target = bundle.create_targets(OnlyInMemoryAppliedProjectionLedger())[component]
    assert fresh_target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.RECOVERED
    assert only_test_runtime_authority_digest(bundle.environment) == before_conflict

    invalid_projection = next(
        item for item in bundle.transaction.projections if item.identity.component is not component
    )
    invalid_context = OnlyExecutionProjectionApplyContext(
        context.transaction_id,
        context.execution_sequence,
        context.fact,
        invalid_projection,
    )
    assert target.apply_execution_projection(invalid_context).status is OnlyProjectionApplyStatus.INVALID_COMPONENT
    assert only_test_runtime_authority_digest(bundle.environment) == before_conflict

    state_bundle = only_test_projection_target_bundle()
    state_projection = next(
        item for item in state_bundle.transaction.projections if item.identity.component is component
    )
    object.__setattr__(state_projection.identity, "expected_state_hash", "f" * 64)
    state_context = OnlyExecutionProjectionApplyContext(
        state_bundle.transaction.transaction_id,
        state_bundle.transaction.execution_sequence,
        state_bundle.transaction.fact,
        state_projection,
    )
    state_before = only_test_runtime_authority_digest(state_bundle.environment)
    assert (
        state_bundle.targets[component].apply_execution_projection(state_context).status
        is OnlyProjectionApplyStatus.STATE_CONFLICT
    )
    assert only_test_runtime_authority_digest(state_bundle.environment) == state_before


def only_test_assert_all_apply(bundle: OnlyTestProjectionTargetBundle) -> None:
    first = bundle.apply_all()
    assert first.status is OnlyExecutionProjectionBatchStatus.COMPLETED
    assert len(first.applied) == 13
    replay = bundle.apply_all()
    assert replay.status is OnlyExecutionProjectionBatchStatus.COMPLETED
    assert len(replay.idempotent) == 13


def only_test_projection_context(
    bundle: OnlyTestProjectionTargetBundle,
    component: OnlyExecutionProjectionComponent,
) -> OnlyExecutionProjectionApplyContext:
    projection = next(item for item in bundle.transaction.projections if item.identity.component is component)
    return OnlyExecutionProjectionApplyContext(
        bundle.transaction.transaction_id,
        bundle.transaction.execution_sequence,
        bundle.transaction.fact,
        projection,
    )


__all__ = [name for name in globals() if name.startswith("OnlyTest") or name.startswith("only_test_")]
