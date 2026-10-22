"""Exact native-owner and isolated-SDK parity for shared technical Web vectors."""

import pytest

from scripts.chart_study_query_fixture import FIXTURE, NUMERIC_CASES, render, render_numeric_cases

pytestmark = [pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(240)]


def test_chart_query_vector_matches_current_owning_dtos_and_installed_backend() -> None:
    assert FIXTURE.read_text() == render()


def test_installed_numeric_nullability_cases_match_the_registered_backend() -> None:
    assert NUMERIC_CASES.read_text() == render_numeric_cases()
