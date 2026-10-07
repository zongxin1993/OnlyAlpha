"""Compilation is an application consequence, not numeric or Run authority."""

import ast
from pathlib import Path

import pytest

from tests.architecture.test_research_calculation_readiness_boundaries import _assert_boundary, _imports, _package

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ("chart_calculation_compilation.py", "chart_calculation_compilation_ports.py"))
def test_compilation_application_has_no_persistence_run_or_transport_authority(name: str) -> None:
    path = ROOT / "src/onlyalpha/application" / name
    _assert_boundary(
        path,
        (
            "psycopg",
            "onlyalpha.persistence",
            "onlyalpha_http_server",
            "onlyalpha_web_console",
            "onlyalpha.research.command",
            "onlyalpha.research.run.admission",
            "onlyalpha.research.run.store",
            "onlyalpha.calculations",
            "onlyalpha.research.calculation.execution.OnlyResearchCalculationExecutor",
            "onlyalpha.research.artifact",
            "onlyalpha.runtime.research",
        ),
    )
    imports = _imports(ast.parse(path.read_text()), _package(path))
    assert not any(name.startswith("onlyalpha_plugin_") for name in imports)


def test_compilation_postgres_adapter_does_not_own_market_or_numeric_authorities() -> None:
    _assert_boundary(
        ROOT / "src/onlyalpha/persistence/postgres/chart_calculation_compilation_store.py",
        (
            "onlyalpha.market_data",
            "onlyalpha.research.command",
            "onlyalpha.research.run.store",
            "onlyalpha.research.calculation.result_store",
            "onlyalpha.research.calculation.result_v2_store",
            "onlyalpha.research.artifact",
            "onlyalpha.runtime.research",
            "onlyalpha_http_server",
        ),
    )


def test_http_and_web_do_not_wire_compilation_service_or_store() -> None:
    for component in ("onlyalpha-http-server", "onlyalpha-web-console"):
        for path in (ROOT / "packages" / component / "src").rglob("*.py"):
            _assert_boundary(
                path,
                (
                    "onlyalpha.application.chart_calculation_compilation",
                    "onlyalpha.persistence.postgres.chart_calculation_compilation_store",
                ),
            )
