import pytest

from examples.integration_demo.environment import OnlyIntegrationEnvironment
from examples.integration_demo.run_all import SCENARIOS, run_all


@pytest.mark.parametrize("scenario_count", range(1, len(SCENARIOS) + 1))
def test_each_vertical_slice_scenario_is_automated(scenario_count: int) -> None:
    env = OnlyIntegrationEnvironment()
    reports = tuple(scenario(env) for scenario in SCENARIOS[:scenario_count])
    assert len(reports) == scenario_count
    assert reports[-1].passed
    assert reports[-1].scenario_id == f"{scenario_count:03d}"


def test_full_vertical_slice_runs_in_one_environment() -> None:
    reports = run_all()
    assert len(reports) == 12
    assert all(report.passed for report in reports)
