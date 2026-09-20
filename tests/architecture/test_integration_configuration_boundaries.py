from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore

from ._architecture_imports import imported_modules_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "src/onlyalpha/application/integration_configuration.py"
POSTGRES = ROOT / "src/onlyalpha/persistence/postgres"
INTEGRATION_STORE = POSTGRES / "integration_store.py"
CREDENTIALS = POSTGRES / "credentials.py"
CONCRETE_PLUGINS = {
    "onlyalpha_plugin_binance",
    "onlyalpha_plugin_binance_spot",
    "onlyalpha_plugin_binance_usdm",
    "onlyalpha_plugin_miniqmt",
    "onlyalpha_plugin_tushare",
}


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_integration_application_and_postgres_store_are_provider_neutral() -> None:
    for path in (APPLICATION, INTEGRATION_STORE, CREDENTIALS):
        assert not (imported_modules_for_path(path, ROOT) & CONCRETE_PLUGINS), path


def test_plugins_and_web_do_not_import_integration_postgres_authority() -> None:
    forbidden = {
        "onlyalpha.persistence.postgres.integration_store",
        "onlyalpha.persistence.postgres.credentials",
    }
    roots = (ROOT / "plugs", ROOT / "packages/onlyalpha-http-server")

    violations = {
        str(path.relative_to(ROOT)): sorted(imported_modules_for_path(path, ROOT) & forbidden)
        for root in roots
        for path in _python_files(root)
        if imported_modules_for_path(path, ROOT) & forbidden
    }
    assert violations == {}


def test_l2a_does_not_bind_runtime_research_or_backtest_to_integration_revision() -> None:
    forbidden = {
        "onlyalpha.application.integration_configuration",
        "onlyalpha.persistence.postgres.integration_store",
    }
    roots = (
        ROOT / "src/onlyalpha/runtime",
        ROOT / "src/onlyalpha/research",
        ROOT / "src/onlyalpha/backtest",
    )

    violations = {
        str(path.relative_to(ROOT)): sorted(imported_modules_for_path(path, ROOT) & forbidden)
        for root in roots
        for path in _python_files(root)
        if imported_modules_for_path(path, ROOT) & forbidden
    }
    assert violations == {}


def test_schema_has_no_integration_type_table_and_store_has_no_revision_update_surface() -> None:
    sql = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "database/postgres/migrations").glob("*.sql"))
    )
    public_methods = {name for name in dir(OnlyPostgresIntegrationStore) if not name.startswith("_")}

    assert re.search(r"CREATE\s+TABLE\s+integration_type\b", sql, re.IGNORECASE) is None
    assert not ({"update_revision", "save_revision", "replace_revision"} & public_methods)


def test_core_has_one_credential_authority_and_new_business_paths_do_not_read_environment() -> None:
    authority_classes: list[tuple[str, str]] = []
    for path in _python_files(ROOT / "src/onlyalpha"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        authority_classes.extend(
            (str(path.relative_to(ROOT)), node.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name.endswith("CredentialAuthority")
        )

    assert authority_classes == [
        ("src/onlyalpha/persistence/postgres/credentials.py", "OnlyPostgresCredentialAuthority")
    ]
    for path in (APPLICATION, INTEGRATION_STORE, CREDENTIALS):
        source = path.read_text(encoding="utf-8")
        assert "os.getenv" not in source and "os.environ" not in source
