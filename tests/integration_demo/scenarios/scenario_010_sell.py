from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    result = env.submit_and_fill_sell()
    assert result.status.value == "APPLIED"
    assert env.sell_order is not None and env.sell_order.order_id is not None
    assert env.runtime.order_manager.require_snapshot(env.sell_order.order_id).status.value == "FILLED"
    assert env.runtime.position_manager.closed()
    return env.report_builder.scenario("010", "卖出", "卖单经过 Risk、Position Reservation 与完整成交链")
