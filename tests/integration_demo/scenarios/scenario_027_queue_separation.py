from tests.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    assert env.market_data_inbound_queue is not env.runtime.broker_inbound_queue
    return env.report_builder.scenario("027", "MarketData and Broker queues are separate")
