from tests.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    env.assert_core_invariants()
    snapshot = env.final_snapshot()
    assert snapshot.event_trace
    return env.report_builder.scenario("012", "最终 Snapshot", "跨组件不变量与事实 Event Trace 一致")
