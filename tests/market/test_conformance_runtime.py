from pathlib import Path

from onlyalpha.market.conformance import (
    OnlyMarketCapabilityRequirement,
    OnlyMarketConformancePack,
    OnlyMarketConformancePackId,
    OnlyMarketConformancePackRegistry,
    OnlyMarketConformancePackVersion,
    OnlyMarketConformanceRunner,
    OnlyMarketConformanceRunRequest,
    OnlyMarketConformanceScenarioBinding,
    OnlyMarketConformanceStatus,
)
from onlyalpha.market.models import OnlyMarketProfileId
from onlyalpha.scenario import OnlyMarketScenarioParser, OnlyMarketScenarioRunner


def test_pack_coverage_is_earned_by_formal_scenario_result(tmp_path) -> None:
    scenario = OnlyMarketScenarioParser().load(Path(__file__).parents[2] / "examples/scenarios/generic_t0_cash.yaml")
    packs = OnlyMarketConformancePackRegistry()
    packs.register(
        OnlyMarketConformancePack(
            OnlyMarketConformancePackId("GENERIC_T0_CASH"),
            OnlyMarketConformancePackVersion("1.0"),
            OnlyMarketProfileId("GENERIC_T0_CASH"),
            ("1.0",),
            (OnlyMarketConformanceScenarioBinding(str(scenario.scenario_id), str(scenario.version)),),
            (OnlyMarketCapabilityRequirement("t0_asset_availability", (str(scenario.scenario_id),)),),
        )
    )
    runner = OnlyMarketConformanceRunner(
        packs,
        {(str(scenario.scenario_id), str(scenario.version)): scenario},
        OnlyMarketScenarioRunner(),
    )

    result = runner.run(OnlyMarketConformanceRunRequest("GENERIC_T0_CASH", tmp_path))

    assert result.status is OnlyMarketConformanceStatus.PASSED
    assert result.coverage[0].covered
    assert result.coverage[0].passed_scenario_ids == (str(scenario.scenario_id),)
    assert (result.artifact_path / "pack_summary.json").is_file()  # type: ignore[operator]
