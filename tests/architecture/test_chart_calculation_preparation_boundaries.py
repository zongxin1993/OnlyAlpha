"""Input preparation stops before Specification, Run and numeric execution."""

from pathlib import Path

import pytest

from tests.architecture.test_research_calculation_readiness_boundaries import _assert_boundary

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "path",
    [
        "src/onlyalpha/application/chart_calculation_preparation.py",
        "src/onlyalpha/persistence/postgres/chart_calculation_preparation_store.py",
    ],
)
def test_preparation_has_no_execution_or_transport_dependencies(path: str) -> None:
    _assert_boundary(
        ROOT / path,
        (
            "onlyalpha_http_server",
            "onlyalpha_web_console",
            "onlyalpha.calculations",
            "onlyalpha.research.specification",
            "onlyalpha.research.command",
            "onlyalpha.research.execution",
            "onlyalpha.research.calculation",
            "onlyalpha.research.result",
            "onlyalpha.research.artifact",
            "onlyalpha.runtime.research",
        ),
    )
