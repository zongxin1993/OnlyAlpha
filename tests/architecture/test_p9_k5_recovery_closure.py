import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]


def _imports(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return frozenset(imports)


def test_kernel_remains_transport_and_postgres_neutral() -> None:
    forbidden = ("psycopg", "fastapi", "starlette", "onlyalpha_http_server")
    for path in (ROOT / "src/onlyalpha/kernel").glob("*.py"):
        assert not any(item.startswith(forbidden) for item in _imports(path)), path


def test_legacy_submission_table_is_not_an_active_production_authority() -> None:
    users: list[Path] = []
    for root in (ROOT / "src", ROOT / "packages"):
        for path in root.rglob("*.py"):
            if "research_run_submission" in path.read_text(encoding="utf-8"):
                users.append(path)
    assert users == []
    migration = (ROOT / "database/postgres/migrations/0012_product_command_receipt.sql").read_text()
    assert "DROP TABLE research_run_submission" in migration


def test_product_command_identity_does_not_enter_semantic_fingerprint_modules() -> None:
    semantic_roots = (
        ROOT / "src/onlyalpha/research/dataset",
        ROOT / "src/onlyalpha/research/calculation",
        ROOT / "src/onlyalpha/research/result",
        ROOT / "src/onlyalpha/strategy/revision.py",
        ROOT / "src/onlyalpha/strategy/freeze_relation.py",
    )
    paths: list[Path] = []
    for root in semantic_roots:
        paths.extend((root,) if root.is_file() else root.glob("*.py"))
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "OnlyProductCommand" not in source
        assert "Idempotency-Key" not in source


def test_production_kernel_composes_guard_and_strategy_recovery() -> None:
    source = (ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server/main.py").read_text(encoding="utf-8")
    assert "authority_guard=OnlyPostgresKernelAuthorityGuard(operational_dsn)" in source
    assert "strategy_projection_reconciliation" in source
    assert ".reconcile_all()" in source
