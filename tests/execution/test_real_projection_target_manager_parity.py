from __future__ import annotations

import pytest

from tests.execution.support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    only_test_generic_t0_legacy_environment,
)
from tests.execution.support.manager_authority_digest import _stable
from tests.execution.targets.support import only_test_assert_all_apply, only_test_projection_target_bundle
from tests.integration_demo.environment import OnlyIntegrationEnvironment

SCENARIOS = (
    OnlyTestGenericT0Scenario("new-zero-fee", fee_enabled=False),
    OnlyTestGenericT0Scenario("new-nonzero-fee"),
    OnlyTestGenericT0Scenario("excess-reservation", fill_price="9.90"),
    OnlyTestGenericT0Scenario("existing-position", fill_price="12.00", existing_position=True),
)


def _projection_authority(environment: OnlyIntegrationEnvironment) -> object:
    runtime = environment.runtime
    orders = runtime.order_manager
    positions = runtime.position_manager
    allocations = runtime.allocation_manager
    accounts = runtime.account_manager
    ledgers = runtime.strategy_ledger_manager
    risk = runtime.risk_service
    ledger_lines = {
        key: tuple(sorted(entity._valuation_lines.values(), key=lambda item: str(item.instrument_id)))
        for key, entity in ledgers._ledgers.items()
    }
    return _stable(
        (
            vars(orders),
            (
                positions.snapshot_all(),
                positions.closed(),
                positions._trade_fingerprints,
                positions._cycles,
                positions._event_sequence,
                positions._repository._items,
            ),
            (
                allocations.snapshot_all(),
                allocations.closed(),
                allocations.unallocated(),
                allocations._trade_fingerprints,
                allocations._cycles,
                allocations._repository._items,
            ),
            (
                accounts.list_accounts(),
                accounts._trade_ids,
                accounts._fee_ids,
                accounts._cash_change_ids,
                accounts._valuation_versions,
                accounts._event_sequence,
                accounts._repository._snapshots,
                accounts._reservation_manager._reservations,
            ),
            (
                ledgers.list_ledgers(),
                ledger_lines,
                ledgers._scope_index,
                ledgers._trade_fingerprints,
                ledgers._fee_ids,
                ledgers._cash_flow_ids,
                ledgers._valuation_versions,
                ledgers._event_sequence,
                ledgers._equity_sequence,
                ledgers._equity_timelines,
                ledgers._repository.snapshots,
                ledgers._repository.cash_entries,
                ledgers._repository.fee_entries,
                ledgers._repository.reservations,
                ledgers._cash_reserved,
            ),
            (
                risk._state._snapshots,
                risk._state._snapshot_versions,
                risk.reservations.snapshot_all(),
                risk.reservations._sequence,
                risk.reservations._reservation_id_by_order_id,
                risk._event_sequence,
            ),
            (
                runtime.settlement_manager._pending,
                runtime.settlement_manager.records,
                runtime.settlement_manager.sequence_head,
            ),
            (
                runtime.fee_manager.records,
                runtime.fee_manager._instruction_keys,
                runtime.fee_manager.sequence_head,
            ),
            vars(runtime.account_performance_projector),
        )
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.name)
def test_real_targets_restore_complete_legacy_manager_authority(scenario: OnlyTestGenericT0Scenario) -> None:
    legacy, _ = only_test_generic_t0_legacy_environment(scenario)
    replay = only_test_projection_target_bundle(scenario)
    only_test_assert_all_apply(replay)
    assert _projection_authority(replay.environment) == _projection_authority(legacy)
