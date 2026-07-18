from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    result = env.submit_buy()
    assert result.created and result.submitted and result.snapshot is not None
    assert env.runtime.broker_gateway is not None
    assert len(env.runtime.broker_gateway.query_orders(result.snapshot.account_id)) == 1
    return env.report_builder.scenario("003", "Order 提交", "Cluster 仅通过 ctx.orders.submit，Broker 仅确认请求已接收")
