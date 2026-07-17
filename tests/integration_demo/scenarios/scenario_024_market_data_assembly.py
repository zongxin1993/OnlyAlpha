from tests.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    assert env.market_data_processor is env.runtime.market_data_processor
    assert env.historical_replay_service is env.runtime.historical_replay_service
    return env.report_builder.scenario("024", "MarketData resources are Runtime-owned")
