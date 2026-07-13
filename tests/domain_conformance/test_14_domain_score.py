from examples.domain_conformance.scoring import OnlyDomainConformanceScore


def test_score_has_no_veto_and_recommends_next_phase() -> None:
    score = OnlyDomainConformanceScore.current_assessment()
    assert score.total == 97
    assert not score.vetoes
    assert score.recommend_runtime and score.recommend_backtest
