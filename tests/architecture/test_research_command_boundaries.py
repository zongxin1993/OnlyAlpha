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
    root = Path("packages/api/onlyalpha-api/src/onlyalpha_api")
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


def test_portable_artifact_composition_has_no_postgres_or_run_dependency() -> None:
    source = Path("packages/api/onlyalpha-api/src/onlyalpha_api/artifact_main.py").read_text()
    assert "postgres" not in source.lower()
    assert "OnlyResearchCommand" not in source
    assert "OnlyResearchRun" not in source


def test_command_api_does_not_return_artifact_or_result_content() -> None:
    source = "\n".join(
        Path(f"packages/api/onlyalpha-api/src/onlyalpha_api/research/{name}").read_text()
        for name in ("run_schema.py", "run_routes.py")
    )
    for forbidden in ("statistics_rows", "series", "parquet", "artifact_manifest", "result_content"):
        assert forbidden not in source.lower()
