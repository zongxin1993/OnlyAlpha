from .environment import OnlyIntegrationEnvironment
from .scenarios.scenario_014_partial_fill import run as run_partial_fill
from .scenarios.scenario_023_partial_fill_then_cancel import run as run_partial_fill_then_cancel


def test_scenario_014_uses_formal_partial_fill_transaction() -> None:
    report = run_partial_fill(OnlyIntegrationEnvironment())
    assert report.passed
    assert report.scenario_id == "014"


def test_scenario_023_cancels_the_remaining_fill_plan() -> None:
    report = run_partial_fill_then_cancel(OnlyIntegrationEnvironment())
    assert report.passed
    assert report.scenario_id == "023"
