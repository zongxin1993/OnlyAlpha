from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    result = env.fill_buy()
    assert result.order.current_status.value == "FILLED"
    assert result.position is not None and result.position.changed
    assert result.ledger is not None and result.ledger.changed
    return env.report_builder.scenario("005", "买单成交", "标准化 Fill 进入 Runtime 单写入者编排")
