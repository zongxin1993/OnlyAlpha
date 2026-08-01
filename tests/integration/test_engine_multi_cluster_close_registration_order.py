from onlyalpha.result import only_backtest_business_projection
from tests.integration.test_engine_multi_cluster_close_cost_authority import _run


def test_multi_cluster_close_is_independent_of_registration_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, first = _run(tmp_path / "first")
    _, second = _run(tmp_path / "second", reverse=True)

    assert first.status == second.status == "COMPLETED"
    assert first.determinism_fingerprint == second.determinism_fingerprint
    assert only_backtest_business_projection(first.runtime_results[0]) == only_backtest_business_projection(
        second.runtime_results[0]
    )
