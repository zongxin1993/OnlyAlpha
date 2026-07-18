from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    records = env.market_data_audit_store.records()
    assert records and [item.processing_sequence for item in records] == list(range(1, len(records) + 1))
    return env.report_builder.scenario("026", "Source/version/quality audit is complete")
