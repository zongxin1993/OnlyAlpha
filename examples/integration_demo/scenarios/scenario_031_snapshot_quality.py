from examples.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    assert env.cluster.snapshots
    assert all("UNADJUSTED" in snapshot.quality_flags for snapshot in env.cluster.snapshots)
    return env.report_builder.scenario("031", "Input quality reaches immutable Snapshot")
