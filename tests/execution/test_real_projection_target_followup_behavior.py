from onlyalpha.execution import (
    OnlyExecutionProjectionComponent,
    OnlyFeeExecutionProjection,
    OnlySettlementExecutionProjection,
    only_execution_trade_fingerprints,
)
from onlyalpha.execution.applied_projection import OnlyExecutionProjectionApplyContext
from onlyalpha.fee import OnlyFeeInstruction
from onlyalpha.market.runtime_rules import OnlySettlementRuntimeInstruction
from tests.execution.targets.support import only_test_assert_all_apply, only_test_projection_target_bundle


def test_replayed_dedup_cycles_and_sequences_drive_followup_behavior() -> None:
    bundle = only_test_projection_target_bundle()
    only_test_assert_all_apply(bundle)
    runtime = bundle.environment.runtime
    transaction = bundle.transaction
    position = next(
        item for item in transaction.projections if item.identity.component is OnlyExecutionProjectionComponent.POSITION
    )
    allocation = next(
        item
        for item in transaction.projections
        if item.identity.component is OnlyExecutionProjectionComponent.ALLOCATION
    )
    context = OnlyExecutionProjectionApplyContext(
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

    settlement = next(item for item in transaction.projections if isinstance(item, OnlySettlementExecutionProjection))
    settlement_state = settlement.after
    next_settlement = OnlySettlementRuntimeInstruction(
        f"{settlement_state.instruction_id}-next",
        str(settlement_state.instrument_id),
        f"{settlement_state.source_trade_id}-next",
        settlement_state.asset_quantity,
        settlement_state.cash_amount.amount,
        settlement_state.asset_available_on,
        settlement_state.cash_trade_available_on,
        settlement_state.cash_withdrawable_on,
        settlement_state.legal_settlement_on,
        str(settlement_state.account_id),
        str(settlement_state.source_order_id),
    )
    runtime.settlement_manager.register(next_settlement)
    emitted = runtime.settlement_manager.advance(settlement_state.legal_settlement_on)
    assert emitted[-1].sequence == settlement_state.record_sequence_head + 1

    fee = next(item for item in transaction.projections if isinstance(item, OnlyFeeExecutionProjection))
    replay = fee.after.instruction
    next_fee = OnlyFeeInstruction(
        f"{replay.instruction_id}-next",
        replay.runtime_id,
        replay.cluster_id,
        replay.account_id,
        replay.order_id,
        f"{replay.trade_id}-next",
        fee.after.fee_breakdown,
        replay.calculation_source,
        replay.created_at.to_datetime(),
        f"{replay.idempotency_key}-next",
    )
    before_sequence = runtime.fee_manager.sequence_head
    records = runtime.fee_manager.apply(next_fee, instrument_id=str(transaction.fact.instrument_id))
    assert records[0].sequence == before_sequence + 1
    assert runtime.fee_manager.apply(next_fee, instrument_id=str(transaction.fact.instrument_id)) == ()


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
