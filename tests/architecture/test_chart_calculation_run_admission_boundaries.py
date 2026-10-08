"""Typed queue admission grants neither numerical nor external transport authority."""

from pathlib import Path

import pytest

from tests.architecture._product_authority_contract import load_authority_contract
from tests.architecture.test_research_calculation_readiness_boundaries import _assert_boundary

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "relative",
    [
        "src/onlyalpha/application/chart_calculation_run_admission.py",
        "src/onlyalpha/persistence/postgres/research_chart_calculation_run_admission_store.py",
    ],
)
def test_chart_run_handoff_cannot_execute_or_publish(relative: str) -> None:
    _assert_boundary(
        ROOT / relative,
        (
            "onlyalpha.calculations",
            "onlyalpha.research.calculation.result_store",
            "onlyalpha.research.calculation.result_v2_store",
            "onlyalpha.research.calculation.execution.OnlyResearchCalculationExecutor",
            "onlyalpha.research.result.result_store",
            "onlyalpha.research.artifact",
            "onlyalpha.runtime.research",
            "onlyalpha_http_server",
        ),
    )


def test_transport_cannot_wire_internal_chart_run_handoff() -> None:
    for path in (ROOT / "packages/onlyalpha-http-server/src").rglob("*.py"):
        _assert_boundary(
            path,
            (
                "onlyalpha.application.chart_calculation_run_admission",
                "onlyalpha.persistence.postgres.research_chart_calculation_run_admission_store",
            ),
        )


def test_chart_run_writer_is_the_existing_research_operational_actor() -> None:
    contract = load_authority_contract(ROOT / "docs/architecture/product_authority_contract.toml")
    path = "src/onlyalpha/persistence/postgres/research_chart_calculation_run_admission_store.py"
    assert contract.is_sensitive_path(path)
    actor = contract.classify_path(path)
    assert actor.name == "RESEARCH_APPLICATION" and actor.production
    assert "C01" in actor.allowed_capabilities
