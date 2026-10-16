"""Exact installed producer parity for the shared Web mutation vector."""

from scripts.chart_study_query_fixture import FIXTURE, NUMERIC_CASES, render, render_numeric_cases


def test_chart_query_vector_matches_current_owning_dtos_and_installed_backend():
    assert FIXTURE.read_text() == render()


def test_installed_numeric_nullability_cases_match_the_registered_backend():
    assert NUMERIC_CASES.read_text() == render_numeric_cases()
