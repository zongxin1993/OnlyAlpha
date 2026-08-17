from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def _imports(root: Path) -> set[str]:
    imports: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_research_run_domain_has_no_database_transport_scheduler_or_trading_dependency() -> None:
    imports = _imports(Path("src/onlyalpha/research/run"))
    forbidden = ("psycopg", "sqlalchemy", "fastapi", "pydantic", "onlyalpha.persistence", "onlyalpha.runtime")
    assert not {item for item in imports if item.startswith(forbidden)}
    source = "\n".join(path.read_text() for path in Path("src/onlyalpha/research/run").glob("*.py"))
    for token in ("SKIP LOCKED", "heartbeat", "lease_owner", "worker_id", "retry_count"):
        assert token not in source


def test_store_port_cannot_arbitrarily_save_or_patch_run() -> None:
    source = Path("src/onlyalpha/research/run/store.py").read_text()
    assert "def create_queued(" in source
    assert "def commit_transition(" in source
    assert "def save(" not in source
    assert "def update(" not in source


def test_research_run_is_exported_without_changing_specification_or_semantic_authorities() -> None:
    root = Path("src/onlyalpha/research/__init__.py").read_text()
    assert "from onlyalpha.research.run import *" in root
    assert not Path("src/onlyalpha/research/run").joinpath("result_store.py").exists()
    assert not Path("src/onlyalpha/research/run").joinpath("dataset_store.py").exists()
