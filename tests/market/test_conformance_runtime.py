from pathlib import Path

import yaml

from onlyalpha.scenario import OnlyMarketScenarioParser, OnlyMarketScenarioRunner, OnlyMarketScenarioRunRequest
from tests.scenario.test_scenario_core import _seed_scenario_strategy


def test_generic_product_coverage_is_earned_by_formal_scenario_result(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "tests/fixtures/scenarios/generic_t0_cash.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["strategy_fingerprint"] = _seed_scenario_strategy(tmp_path)
    scenario = OnlyMarketScenarioParser().parse(payload)
    result = OnlyMarketScenarioRunner().run(OnlyMarketScenarioRunRequest(scenario, tmp_path))

    assert result.status == "PASSED"
    assert result.result_fingerprint
    assert result.artifact_path is not None
    assert (result.artifact_path / "manifest.json").is_file()
