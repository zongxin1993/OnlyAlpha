from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.kernel.command import OnlyProductCommandDispatcher
from onlyalpha.kernel.query import OnlyProductQueryDispatcher
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from tests.architecture._architecture_imports import imported_modules_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
KERNEL = ROOT / "src/onlyalpha/kernel"
PRODUCT_COMPOSITION = ROOT / "src/onlyalpha/application/product_boundary.py"


def test_kernel_dispatchers_are_transport_and_domain_neutral() -> None:
    forbidden = (
        "fastapi",
        "starlette",
        "pydantic",
        "uvicorn",
        "onlyalpha_http_server",
        "onlyalpha.engine",
        "onlyalpha.persistence",
        "onlyalpha.research",
        "onlyalpha.runtime",
        "onlyalpha.strategy",
    )
    for filename in ("command.py", "query.py"):
        assert not any(name.startswith(forbidden) for name in imported_modules_for_path(KERNEL / filename, ROOT))


def test_command_and_query_have_separate_minimal_surfaces() -> None:
    assert {name for name in vars(OnlyProductCommandDispatcher) if not name.startswith("_")} == {"dispatch"}
    assert {name for name in vars(OnlyProductQueryDispatcher) if not name.startswith("_")} == {"dispatch"}
    assert "assert_mutation_ready" in (KERNEL / "command.py").read_text(encoding="utf-8")
    assert "assert_mutation_ready" not in (KERNEL / "query.py").read_text(encoding="utf-8")


def test_research_query_service_receives_only_read_capability() -> None:
    annotation = OnlyResearchRunQueryService.__init__.__annotations__["store"]
    assert annotation == "OnlyResearchRunReader"
    assert {name for name in vars(OnlyResearchRunQueryService) if not name.startswith("_")} == {
        "get_run",
        "list_runs",
    }


def test_research_product_composition_remains_thin_and_transport_neutral() -> None:
    source = PRODUCT_COMPOSITION.read_text(encoding="utf-8")
    assert source.count("OnlyProductCommandDispatcher(") == 1
    assert source.count("OnlyProductQueryDispatcher(") == 1
    assert "submit_research_run(" in source
    assert "request_research_run_cancellation(" in source
    assert "get_run(" in source
    assert "list_runs(" in source
    assert not any(
        name.startswith(("fastapi", "pydantic", "onlyalpha_http_server"))
        for name in imported_modules_for_path(PRODUCT_COMPOSITION, ROOT)
    )
