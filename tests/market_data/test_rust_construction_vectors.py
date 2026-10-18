"""Common valid semantics against independent records, without Runtime or wire-parity claims."""

import json
from pathlib import Path

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.core.clock import OnlyVirtualClock
from onlyalpha.domain.market import OnlyBar
from onlyalpha.market_data.aggregation.compiler import OnlyProviderInputLane
from onlyalpha.market_data.aggregation.time_bar import OnlyTimeBarAggregator
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionIdentity,
    OnlyBarConstructionRecipe,
    OnlyBarConstructionRequirement,
    OnlyBarResolutionPlan,
    OnlyMarketDataConstructionGraph,
    OnlyMarketDataConstructionLane,
)

DATA = Path(__file__).resolve().parents[2] / "test-data/market-data-construction"


def test_independent_current_records_and_lane_hashes() -> None:
    readers = {
        "recipe": OnlyBarConstructionRecipe,
        "requirement": OnlyBarConstructionRequirement,
        "graph": OnlyMarketDataConstructionGraph,
        "plan": OnlyBarResolutionPlan,
        "identity": OnlyBarConstructionIdentity,
    }
    for line in (DATA / "models-v1.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["family"] == "compiled":
            graph = OnlyMarketDataConstructionGraph.from_dict(row["record"])
            assert OnlyProviderInputLane(graph.provider_inputs[0], row["source"]).lane_id == row["provider"]
            actual = sorted(
                OnlyMarketDataConstructionLane(edge.target, edge.recipe.fingerprint, row["source"]).lane_id
                for edge in graph.derived_dependencies
            )
            assert actual == [lane["lane_id"] for lane in row["lanes"]]
            for lane in row["lanes"]:
                assert OnlyMarketDataConstructionLane.from_dict(lane["record"]).lane_id == lane["lane_id"]
        else:
            result = readers[row["family"]].from_dict(row["record"])
            assert result.to_dict() == row["record"]
            assert only_canonical_fingerprint(result.to_dict()) == row["sha256"]


def test_independent_time_bar_outputs(shanghai_calendar) -> None:
    for line in (DATA / "operations-v1.jsonl").read_text().splitlines():
        row = json.loads(line)
        # Real Python constructor and process path, with an explicit deterministic logical clock.
        graph = OnlyMarketDataConstructionGraph.from_dict(
            {"schema_version": 1, "provider_inputs": [row["edge"]["source"]], "derived_dependencies": [row["edge"]]}
        )
        edge = graph.derived_dependencies[0]
        bars = [OnlyBar.from_dict(record) for record in row["inputs"]]
        clock = OnlyVirtualClock(bars[0].bar_end)
        executor = OnlyTimeBarAggregator(edge.source, edge.target, shanghai_calendar, clock)
        output = []
        for bar in bars:
            clock.advance_to(bar.bar_end)
            result = executor.process(bar)
            if result is not None:
                output.append(result.to_record())
        assert output == row["expected"]
