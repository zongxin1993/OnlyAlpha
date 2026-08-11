from pathlib import Path

from onlyalpha.scenario import OnlyMarketScenarioParser, OnlyMarketScenarioRunner, OnlyMarketScenarioRunRequest


def test_generic_product_coverage_is_earned_by_formal_scenario_result(tmp_path: Path) -> None:
    scenario = OnlyMarketScenarioParser().load(
        Path(__file__).parents[2] / "tests/fixtures/scenarios/generic_t0_cash.yaml"
    )
    result = OnlyMarketScenarioRunner().run(OnlyMarketScenarioRunRequest(scenario, tmp_path))

    assert result.status == "PASSED"
    assert result.result_fingerprint
    assert result.artifact_path is not None
    assert (result.artifact_path / "manifest.json").is_file()
