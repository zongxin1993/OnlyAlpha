from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def _imports(root: Path) -> set[str]:
    result: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                result.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                result.add(node.module)
    return result


def test_command_core_is_transport_and_execution_neutral() -> None:
    imports = _imports(Path("src/onlyalpha/research/command"))
    forbidden = (
        "fastapi",
        "pydantic",
        "uvicorn",
        "psycopg",
        "onlyalpha.persistence",
        "onlyalpha.engine",
        "onlyalpha.runtime",
        "onlyalpha.research.execution",
        "onlyalpha.research.artifact",
        "onlyalpha.research.query",
    )
    assert not {name for name in imports if name.startswith(forbidden)}


def test_run_http_adapter_cannot_start_execution_or_modify_attempt_authority() -> None:
    root = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    for forbidden in (
        "OnlyResearchWorkerService",
        "OnlyResearchScheduler",
        "OnlyPostgresResearchExecutionStore",
        "claim_next(",
        "heartbeat(",
        "renew(",
        "expire_next(",
        "OnlyEngine(",
    ):
        assert forbidden not in source


def test_standalone_artifact_composition_is_absent() -> None:
    assert not Path("packages/onlyalpha-http-server/src/onlyalpha_http_server/artifact_main.py").exists()


def test_command_api_does_not_return_artifact_or_result_content() -> None:
    source = "\n".join(
        Path(f"packages/onlyalpha-http-server/src/onlyalpha_http_server/research/{name}").read_text()
        for name in ("run_schema.py", "run_routes.py")
    )
    for forbidden in ("statistics_rows", "series", "parquet", "artifact_manifest", "result_content"):
        assert forbidden not in source.lower()


def test_production_research_command_composition_requires_read_to_act_authorities() -> None:
    source = Path("packages/onlyalpha-http-server/src/onlyalpha_http_server/main.py").read_text(encoding="utf-8")
    composition = source[source.index("command = OnlyResearchCommandService(") : source.index("research_queries =")]
    for required in (
        "novelty_decisions=",
        "memory_builder=",
        "memory_revisions=",
        "command_admissions=",
        "runtime_generation_resolver=",
    ):
        assert required in composition


def test_product_and_search_research_creation_share_the_command_service_gate() -> None:
    product = Path("src/onlyalpha/application/product_boundary.py").read_text(encoding="utf-8")
    symbolic = Path("src/onlyalpha/research/search/symbolic/product.py").read_text(encoding="utf-8")
    parameter = Path("src/onlyalpha/research/search/parameter/integration.py").read_text(encoding="utf-8")
    assert "commands.submit_research_run(" in product
    assert "self.commands.submit_research_run(" in symbolic
    assert "self.commands.submit_research_run(" in parameter
    for source in (product, symbolic, parameter):
        assert "create_queued_with_receipt(" not in source
        assert "create_queued_with_novelty_admission(" not in source
