"""An ephemeral numeric projection is neither Run execution nor publication authority."""

import ast
from pathlib import Path

import pytest

from tests.architecture.test_research_calculation_readiness_boundaries import _assert_boundary

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).resolve().parents[2]


def test_chart_projection_has_no_mutation_or_provider_implementation_authority():
    _assert_boundary(
        ROOT / "src/onlyalpha/application/chart_calculation_execution.py",
        (
            "onlyalpha.persistence",
            "onlyalpha_plugin_indicators",
            "onlyalpha.calculations",
            "onlyalpha.research.calculation.result_store",
            "onlyalpha.research.calculation.result_v2_store",
            "onlyalpha.research.calculation.execution_evidence_store",
            "onlyalpha.research.result.result_store",
            "onlyalpha.research.artifact",
            "onlyalpha.runtime.research",
            "onlyalpha.engine",
            "onlyalpha_http_server",
        ),
    )
    tree = ast.parse((ROOT / "src/onlyalpha/application/chart_calculation_execution.py").read_text())
    forbidden = {
        "commit",
        "commit_or_replay",
        "claim_next",
        "heartbeat",
        "transition",
        "bind_new_work",
        "release_work",
        "_execute_verified_v2",
    }
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in forbidden
    ]


def test_transport_and_legacy_worker_do_not_wire_numeric_chart_port():
    paths = list((ROOT / "packages/onlyalpha-http-server/src").rglob("*.py"))
    paths += list((ROOT / "src/onlyalpha/research/execution").rglob("*.py"))
    paths += [ROOT / "src/onlyalpha/research/worker_main.py"]
    for path in paths:
        _assert_boundary(path, ("onlyalpha.application.chart_calculation_execution",))
        assert "execute_chart_calculation" not in path.read_text()


def test_numeric_request_issuance_remains_inside_owning_application_producer():
    owner = ROOT / "src/onlyalpha/application/chart_calculation_execution.py"
    for path in [*(ROOT / "src").rglob("*.py"), *(ROOT / "packages").glob("*/src/**/*.py")]:
        if path == owner:
            continue
        tree = ast.parse(path.read_text())
        assert not [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_OnlyIssuedChartCalculationExecutionRequest"
        ]
