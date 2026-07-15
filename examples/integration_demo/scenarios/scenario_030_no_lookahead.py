from examples.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    assert all(item.update.ts_event.unix_nanos <= item.clock_time_ns for item in env.historical_replay_service.events)
    return env.report_builder.scenario("030", "Replay processing has no future visibility")
