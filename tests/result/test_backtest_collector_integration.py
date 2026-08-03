import pytest

from onlyalpha.collector import OnlyBacktestResultCollector, OnlyResultCollectorError
from tests.support.engine_results import load_engine_result_fixture


def test_collector_formal_result_projection_is_reused_without_engine_execution() -> None:
    fixture = load_engine_result_fixture("minimal_round_trip")
    projection = fixture.result.cluster_results[0]

    assert fixture.result.status == "COMPLETED"
    assert fixture.expected_fill_count == 2
    assert projection["fact_counts"]["executions"] == fixture.expected_fill_count  # type: ignore[index]
    assert projection["result_fingerprint"] == fixture.result_fingerprint
    assert projection["execution"] == {"order_count": 2, "rejected_order_count": 0, "trade_count": 2}
    assert projection["final_positions"] == []
    assert projection["final_account"]


def test_collector_lifecycle_rejects_invalid_access() -> None:
    collector = OnlyBacktestResultCollector()
    with pytest.raises(OnlyResultCollectorError, match="before seal"):
        collector.snapshot()
    collector.start()
    with pytest.raises(OnlyResultCollectorError, match="only once"):
        collector.start()
