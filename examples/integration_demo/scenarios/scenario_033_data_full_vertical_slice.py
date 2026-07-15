from examples.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    env.assert_core_invariants()
    assert env.market_data_audit_store.records()
    return env.report_builder.scenario("033", "DataSource-to-Account full Vertical Slice")
