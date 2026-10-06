"""T1 imports value contracts and persistence ports, never an execution capability."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.architecture.test_research_calculation_readiness_boundaries import _assert_boundary

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).resolve().parents[2]
_FORBIDDEN = (
    "onlyalpha_http_server",
    "onlyalpha_web_console",
    "onlyalpha.market_data",
    "onlyalpha.dataset",
    "onlyalpha.runtime",
    "onlyalpha.research.command",
    "onlyalpha.research.execution",
    "onlyalpha.research.calculation",
    "onlyalpha.research.result",
    "onlyalpha.research.artifact",
    "onlyalpha.calculations",
    "onlyalpha.integrations",
)


@pytest.mark.parametrize("name", ["chart_calculation.py", "chart_calculation_ports.py"])
def test_application_admission_has_no_side_effect_dependencies(name: str) -> None:
    _assert_boundary(ROOT / "src/onlyalpha/application" / name, _FORBIDDEN + ("onlyalpha.persistence", "psycopg"))


def test_postgres_admission_cannot_call_market_data_or_runtime() -> None:
    _assert_boundary(ROOT / "src/onlyalpha/persistence/postgres/chart_calculation_store.py", _FORBIDDEN)
