from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    assert env.market_data_source_registry.contains(env.historical_data_source.source_id)
    assert env.market_data_source_registry.contains(env.market_data_gateway.source_id)
    return env.report_builder.scenario("028", "MarketData sources are explicit and unique")
