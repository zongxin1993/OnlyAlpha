from .support.scenarios import run_all_scenarios


def test_all_ten_market_scenarios_complete() -> None:
    results = run_all_scenarios()
    assert len(results) == 10
    assert all(result.passed for result in results), [result for result in results if not result.passed]
