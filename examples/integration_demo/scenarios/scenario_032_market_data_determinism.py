from examples.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    sequences = [item.source_sequence for item in env.market_data_audit_store.records()]
    assert sequences == sorted(sequences)
    return env.report_builder.scenario("032", "MarketData sequence is deterministic")
