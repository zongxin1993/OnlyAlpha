from onlyalpha.execution import (
    OnlyRuntimeProjectionApplier,
    OnlyRuntimeProjectionBatchStatus,
    OnlyTradeExecutionTransactionPlanner,
)
from tests.execution.support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    only_test_generic_t0_legacy_environment,
    only_test_generic_t0_trade_update,
    only_test_real_trade_planning_context,
)
from tests.execution.targets.support import only_test_projection_target_bundle
from tests.execution.test_real_projection_target_manager_parity import _projection_authority
from tests.integration_demo.environment import DAY_ONE


def test_three_sequential_buy_open_transactions_match_legacy_authority() -> None:
    scenario = OnlyTestGenericT0Scenario("sequential")
    legacy, _ = only_test_generic_t0_legacy_environment(scenario)
    replay = only_test_projection_target_bundle(scenario)
    applier = OnlyRuntimeProjectionApplier(replay.targets)
    assert applier.apply(replay.transaction).status is OnlyRuntimeProjectionBatchStatus.COMPLETED

    for number, minute in ((2, 4), (3, 5)):
        suffix = f"t{number}"
        request_id = f"sequential-{suffix}"
        for environment in (legacy, replay.environment):
            gateway = environment.runtime.broker_gateway
            assert gateway is not None
            gateway.on_bar(environment.make_bar(DAY_ONE, minute, "10.00"))
            gateway.run_due()
            environment.runtime.broker_inbound_queue.drain()
        legacy.submit_buy(request_id=request_id, minute=minute)
        replay.environment.submit_buy(request_id=request_id, minute=minute)
        legacy_update = only_test_generic_t0_trade_update(legacy, scenario, suffix=suffix)
        replay_update = only_test_generic_t0_trade_update(replay.environment, scenario, suffix=suffix)
        assert legacy_update == replay_update
        legacy_result = legacy.runtime.execution_processor.process(legacy_update)
        assert legacy_result.status.value == "APPLIED"
        context = only_test_real_trade_planning_context(replay.environment, replay_update)
        planned = OnlyTradeExecutionTransactionPlanner().prepare(context)
        committed = replay.transaction_store.commit(planned, committed_at=context.prepared_at).transaction
        assert committed.execution_sequence == number
        assert applier.apply(committed).status is OnlyRuntimeProjectionBatchStatus.COMPLETED

    assert len(replay.applied_ledger.records()) == 39
    assert _projection_authority(replay.environment) == _projection_authority(legacy)
