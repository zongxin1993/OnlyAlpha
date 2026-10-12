"""Exact installed producer parity for the shared Web mutation vector."""

from scripts.chart_study_query_fixture import FIXTURE, render


def test_chart_query_vector_matches_current_owning_dtos_and_installed_backend():
    assert FIXTURE.read_text() == render()
