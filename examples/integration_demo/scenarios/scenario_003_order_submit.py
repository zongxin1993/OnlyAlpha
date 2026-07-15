from examples.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    result = env.submit_buy()
    assert result.created and result.submitted and result.snapshot is not None
    assert len(env.runtime.execution_service.submissions) == 1
    return env.report_builder.scenario("003", "Order 提交", "Cluster 仅通过 ctx.orders.submit 提交")
