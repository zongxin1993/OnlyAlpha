from examples.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    assert env.historical_replay_service.events
    assert all(item.update.data_version.value for item in env.historical_replay_service.events)
    return env.report_builder.scenario("025", "Historical Bars used ReplayService")
