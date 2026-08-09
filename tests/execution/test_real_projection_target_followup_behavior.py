from dataclasses import replace

from onlyalpha.execution import (
    OnlyFeeApplicationProjection,
    OnlyRuntimeProjectionComponent,
    only_execution_trade_fingerprints,
)
from onlyalpha.transaction.applied_projection import OnlyRuntimeProjectionApplyContext
from tests.execution.targets.support import only_test_assert_all_apply, only_test_projection_target_bundle


def test_replayed_dedup_cycles_and_sequences_drive_followup_behavior() -> None:
    bundle = only_test_projection_target_bundle()
    only_test_assert_all_apply(bundle)
    runtime = bundle.environment.runtime
    transaction = bundle.transaction
    position = next(
        item for item in transaction.projections if item.identity.component is OnlyRuntimeProjectionComponent.POSITION
    )
    allocation = next(
        item for item in transaction.projections if item.identity.component is OnlyRuntimeProjectionComponent.ALLOCATION
    )
    context = OnlyRuntimeProjectionApplyContext(
        transaction.transaction_id,
        transaction.execution_sequence,
        transaction.fact,
        position,
    )
    fingerprints = set(only_execution_trade_fingerprints(context))
    assert fingerprints <= runtime.position_manager._trade_fingerprints
    assert fingerprints <= runtime.allocation_manager._trade_fingerprints
    assert fingerprints <= runtime.strategy_ledger_manager._trade_fingerprints
    assert runtime.position_manager._cycles[position.after.key] == position.replay.cycle
    assert runtime.allocation_manager._cycles[allocation.after.key] == allocation.replay.cycle
    assert runtime.risk_service.reservations.sequence_head == 1

    fee = next(item for item in transaction.projections if isinstance(item, OnlyFeeApplicationProjection))
    application = fee.after.application
    next_fee = replace(
        application,
        application_id=f"{application.application_id}-next",
        idempotency_key=f"{application.idempotency_key}-next",
    )
    before_sequence = runtime.fee_application_ledger.sequence_head
    records = runtime.fee_application_ledger.apply(
        next_fee, instrument_id=transaction.fact.instrument_id, effective_at=transaction.fact.ts_event
    )
    assert not records or records[0].sequence == before_sequence + 1
    assert (
        runtime.fee_application_ledger.apply(
            next_fee, instrument_id=transaction.fact.instrument_id, effective_at=transaction.fact.ts_event
        )
        == ()
    )


def test_valuation_replay_preserves_versions_and_contiguous_timelines() -> None:
    bundle = only_test_projection_target_bundle()
    only_test_assert_all_apply(bundle)
    runtime = bundle.environment.runtime
    account = runtime.account_manager.list_accounts()[0]
    ledger = runtime.strategy_ledger_manager.list_ledgers()[0]
    valuation = bundle.valuation_authority.get(account.account_id)
    assert valuation is not None
    assert account.version == 10
    assert ledger.version == 12
    assert runtime.account_manager._valuation_versions[account.account_id] == valuation.version
    assert runtime.strategy_ledger_manager._valuation_versions[ledger.key] == valuation.version
    account_points = runtime.account_performance_projector.timeline(account.account_id)
    ledger_points = runtime.strategy_ledger_manager.equity_timeline(ledger.key)
    assert tuple(item.sequence for item in account_points) == tuple(range(1, len(account_points) + 1))
    assert tuple(item.sequence for item in ledger_points) == tuple(range(1, len(ledger_points) + 1))
