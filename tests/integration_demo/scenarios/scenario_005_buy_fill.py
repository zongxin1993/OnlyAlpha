from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    result = env.fill_buy()
    assert result.status.value == "APPLIED"
    assert env.buy_order is not None and env.buy_order.order_id is not None
    assert env.runtime.order_manager.require_snapshot(env.buy_order.order_id).status.value == "FILLED"
    assert env.runtime.position_manager.snapshot_all()
    assert env.runtime.strategy_ledger_manager.list_ledgers()
    return env.report_builder.scenario("005", "买单成交", "标准化 Fill 进入 Runtime 单写入者编排")
