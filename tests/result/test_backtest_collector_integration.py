from pathlib import Path

import pytest

from onlyalpha.collector import OnlyBacktestResultCollector, OnlyResultCollectorError
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig


def _run(target: Path):
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("result-collector"), target))
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster.json")
    return engine.run()


def test_collector_reads_runtime_facts_without_changing_business_result(tmp_path: Path) -> None:
    first = _run(tmp_path / "first")
    second = _run(tmp_path / "second")

    assert first.status == second.status == "COMPLETED"
    assert first.determinism_fingerprint == second.determinism_fingerprint
    first_projection = first.cluster_results[0]
    second_projection = second.cluster_results[0]
    assert first_projection["fact_counts"] == {
        "signals": 0,
        "order_requests": 2,
        "orders": 2,
        "executions": 2,
        "positions": 0,
        "accounts": 1,
        "equity": 1,
    }
    assert first_projection["result_fingerprint"] == second_projection["result_fingerprint"]
    assert first_projection["execution"] == second_projection["execution"]
    assert first_projection["final_positions"] == second_projection["final_positions"]
    assert first_projection["final_accounts"] == second_projection["final_accounts"]


def test_collector_lifecycle_rejects_invalid_access() -> None:
    collector = OnlyBacktestResultCollector()
    with pytest.raises(OnlyResultCollectorError, match="before seal"):
        collector.snapshot()
    collector.start()
    with pytest.raises(OnlyResultCollectorError, match="only once"):
        collector.start()
