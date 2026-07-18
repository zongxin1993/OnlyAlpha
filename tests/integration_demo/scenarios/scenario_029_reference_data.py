from ..environment import INSTRUMENT_ID, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    assert env.reference_data_source.instrument(INSTRUMENT_ID) == env.instrument
    assert env.reference_data_source.calendar(env.calendar.calendar_id) == env.calendar
    return env.report_builder.scenario("029", "Reference data is a separate candidate source")
