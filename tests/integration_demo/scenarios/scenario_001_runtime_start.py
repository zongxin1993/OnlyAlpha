from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    env.start()
    assert env.runtime.state.value == "RUNNING"
    assert env.cluster.context is not None
    return env.report_builder.scenario("001", "Runtime 启动", "Runtime 与 Cluster 均已启动")
