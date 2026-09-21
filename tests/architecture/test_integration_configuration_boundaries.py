from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore

from ._architecture_imports import imported_modules_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATION = ROOT / "src/onlyalpha/application/integration_configuration.py"
APPLICATION = ROOT / "src/onlyalpha/application/integration_application.py"
PROBE_APPLICATION = ROOT / "src/onlyalpha/application/integration_probe.py"
RUNTIME_APPLICATION = ROOT / "src/onlyalpha/application/integration_runtime.py"
BINANCE_SPOT_PROBE = ROOT / "plugs/onlyalpha-plugin-binance/src/onlyalpha_plugin_binance/spot/data_source/probe.py"
POSTGRES = ROOT / "src/onlyalpha/persistence/postgres"
INTEGRATION_STORE = POSTGRES / "integration_store.py"
PRODUCT_STORE = POSTGRES / "integration_product_store.py"
CREDENTIALS = POSTGRES / "credentials.py"
INTEGRATION_TYPE_CATALOG = ROOT / "src/onlyalpha/application/integration_type_catalog.py"
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
    for path in (
        CONFIGURATION,
        APPLICATION,
        PROBE_APPLICATION,
        RUNTIME_APPLICATION,
        INTEGRATION_STORE,
        PRODUCT_STORE,
        CREDENTIALS,
    ):
        assert not (imported_modules_for_path(path, ROOT) & CONCRETE_PLUGINS), path


def test_runtime_consumers_and_plugins_cannot_import_integration_persistence() -> None:
    forbidden = {
        "onlyalpha.persistence.postgres.integration_store",
        "onlyalpha.persistence.postgres.integration_product_store",
        "onlyalpha.persistence.postgres.integration_probe_store",
        "onlyalpha.persistence.postgres.credentials",
    }
    roots = (
        ROOT / "src/onlyalpha/runtime",
        ROOT / "plugs",
        ROOT / "packages/onlyalpha-agent-orchestrator/src",
    )
    violations = {
        str(path.relative_to(ROOT)): sorted(imported_modules_for_path(path, ROOT) & forbidden)
        for root in roots
        for path in _python_files(root)
        if imported_modules_for_path(path, ROOT) & forbidden
    }

    assert violations == {}


def test_plugins_do_not_import_integration_authority_and_http_routes_stay_transport_only() -> None:
    plugin_forbidden = {
        "onlyalpha.application.integration_application",
        "onlyalpha.persistence.postgres.integration_store",
        "onlyalpha.persistence.postgres.integration_product_store",
        "onlyalpha.persistence.postgres.credentials",
    }
    plugin_violations = {
        str(path.relative_to(ROOT)): sorted(imported_modules_for_path(path, ROOT) & plugin_forbidden)
        for path in _python_files(ROOT / "plugs")
        if imported_modules_for_path(path, ROOT) & plugin_forbidden
    }
    route_root = ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server/integrations"
    route_forbidden = {
        "onlyalpha.persistence.postgres.integration_store",
        "onlyalpha.persistence.postgres.integration_product_store",
        "onlyalpha.persistence.postgres.credentials",
    }
    route_violations = {
        str(path.relative_to(ROOT)): sorted(imported_modules_for_path(path, ROOT) & route_forbidden)
        for path in _python_files(route_root)
        if imported_modules_for_path(path, ROOT) & route_forbidden
    }

    assert plugin_violations == {}
    assert route_violations == {}


def test_integration_http_has_only_declared_probe_and_no_delete_or_master_key_creation_authority() -> None:
    http_root = ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server"
    integration_source = "\n".join(
        path.read_text(encoding="utf-8") for path in _python_files(http_root / "integrations")
    )
    main_source = (http_root / "main.py").read_text(encoding="utf-8")

    assert 'router.delete("/{integration_id}")' not in integration_source
    assert '"/{integration_id}/probe"' in integration_source
    assert '"/{integration_id}/probe-attempts"' in integration_source
    assert '"/{integration_id}/probe-attempts/{probe_attempt_id}"' in integration_source
    assert "/test-connection" not in integration_source
    assert "only_ensure_dev_master_key" not in main_source
    assert "only_load_master_key" in main_source


def test_runtime_research_and_backtest_do_not_bind_integration_revision() -> None:
    forbidden = {
        "onlyalpha.application.integration_configuration",
        "onlyalpha.application.integration_application",
        "onlyalpha.persistence.postgres.integration_store",
        "onlyalpha.persistence.postgres.integration_product_store",
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


def test_web_integration_workspace_is_provider_neutral_and_secret_storage_free() -> None:
    web_root = ROOT / "packages/onlyalpha-web-console/src"
    roots = (web_root / "api/integrations", web_root / "features/data/sources")
    sources = {
        str(path.relative_to(ROOT)): path.read_text(encoding="utf-8").lower()
        for root in roots
        for path in root.rglob("*")
        if path.suffix in {".ts", ".tsx"} and ".test." not in path.name
    }
    provider_tokens = ("binance", "tushare", "miniqmt")
    persistence_tokens = ("localstorage", "sessionstorage", "indexeddb")
    assert {path: token for path, source in sources.items() for token in provider_tokens if token in source} == {}
    assert {path: token for path, source in sources.items() for token in persistence_tokens if token in source} == {}


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
    for path in (CONFIGURATION, APPLICATION, INTEGRATION_STORE, PRODUCT_STORE, CREDENTIALS):
        source = path.read_text(encoding="utf-8")
        assert "os.getenv" not in source and "os.environ" not in source


def test_one_integration_command_service_and_no_second_idempotency_authority() -> None:
    command_services: list[tuple[str, str]] = []
    for path in _python_files(ROOT / "src/onlyalpha"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        command_services.extend(
            (str(path.relative_to(ROOT)), node.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "OnlyIntegrationCommandService"
        )
    sql = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "database/postgres/migrations").glob("*.sql"))
    )

    assert command_services == [
        ("src/onlyalpha/application/integration_application.py", "OnlyIntegrationCommandService")
    ]
    assert re.search(r"CREATE\s+TABLE\s+integration_(?:command|receipt|admission)\b", sql, re.IGNORECASE) is None


def test_integration_type_catalog_does_not_create_a_second_plugin_discovery_path() -> None:
    imports = imported_modules_for_path(INTEGRATION_TYPE_CATALOG, ROOT)
    source = INTEGRATION_TYPE_CATALOG.read_text(encoding="utf-8")

    assert "importlib.metadata" not in imports
    assert "onlyalpha.plugin.discovery" not in imports
    assert "entry_points(" not in source
    assert "only_discover_plugins" not in source


def test_first_party_product_data_source_entry_points_have_permanent_coverage() -> None:
    entry_points: dict[str, str] = {}
    for relative in (
        "plugs/onlyalpha-plugin-binance/pyproject.toml",
        "plugs/onlyalpha-plugin-miniqmt/pyproject.toml",
        "plugs/onlyalpha-plugin-tushare/pyproject.toml",
    ):
        project = tomllib.loads((ROOT / relative).read_text(encoding="utf-8"))["project"]
        entry_points.update(project["entry-points"]["onlyalpha.data_sources"])

    assert entry_points == {
        "binance": "onlyalpha_plugin_binance.spot.data_source.factory:factory",
        "binance-usdm": "onlyalpha_plugin_binance.usdm.data_source:factory",
        "miniqmt": "onlyalpha_plugin_miniqmt.data_source.factory:factory",
        "tushare": "onlyalpha_plugin_tushare.data_source.factory:factory",
    }


def test_integration_application_has_no_probe_transport_or_caller_runtime_fingerprint_authority() -> None:
    imports = imported_modules_for_path(APPLICATION, ROOT)
    product_source = PRODUCT_STORE.read_text(encoding="utf-8")
    tree = ast.parse(APPLICATION.read_text(encoding="utf-8"), filename=str(APPLICATION))
    command_fields = {
        child.target.id
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name.startswith("Only")
        and node.name != "OnlyIntegrationResolvedPublication"
        for child in node.body
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
    }

    assert not (imports & {"httpx", "requests", "socket", "urllib"})
    assert "runtime_configuration_fingerprint" not in command_fields
    assert ".from_draft(" not in product_source


def test_probe_application_has_no_runtime_engine_event_bus_or_provider_transport_dependency() -> None:
    imports = imported_modules_for_path(PROBE_APPLICATION, ROOT)

    assert not (
        imports
        & {
            "onlyalpha.engine",
            "onlyalpha.runtime",
            "onlyalpha.event_bus",
            "httpx",
            "requests",
            "socket",
            "urllib",
        }
    )
    source = PROBE_APPLICATION.read_text(encoding="utf-8")
    assert ".create(request)" not in source


def test_binance_probe_has_no_market_data_authority_or_runtime_resource_dependency() -> None:
    imports = imported_modules_for_path(BINANCE_SPOT_PROBE, ROOT)
    forbidden = (
        "onlyalpha.cache",
        "onlyalpha.engine",
        "onlyalpha.event_bus",
        "onlyalpha.persistence",
        "onlyalpha.research",
        "onlyalpha.runtime",
    )
    assert not {module for module in imports if module.startswith(forbidden)}
