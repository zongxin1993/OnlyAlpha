from onlyalpha.execution import OnlyExecutionProjectionComponent, OnlyTradeExecutionTransactionPlanner

from .factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def test_reductions_are_versioned_hashed_and_economically_consistent() -> None:
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(only_test_generic_t0_trade_planning_context())
    for projection in prepared.projections:
        assert projection.identity.result_version > projection.identity.expected_version
        assert len(projection.identity.expected_state_hash) == 64
        assert len(projection.identity.result_state_hash) == 64
        assert len(projection.identity.payload_hash) == 64
    assert OnlyExecutionProjectionComponent.MARGIN not in {item.identity.component for item in prepared.projections}
