from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    result = env.submit_and_fill_sell()
    assert result.order.current_status.value == "FILLED"
    assert result.position is not None and result.position.changed
    return env.report_builder.scenario("010", "卖出", "卖单经过 Risk、Position Reservation 与完整成交链")
