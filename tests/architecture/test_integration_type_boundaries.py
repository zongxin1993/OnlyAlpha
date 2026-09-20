from pathlib import Path

import pytest

from onlyalpha.plugin.descriptor import OnlyPluginType
from onlyalpha.plugin.integration import OnlyIntegrationCategory

from ._architecture_imports import imported_modules_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
CORE_CONTRACT = ROOT / "src/onlyalpha/plugin/integration.py"
CATALOG = ROOT / "src/onlyalpha/application/integration_type_catalog.py"
HTTP_ROOT = ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server/integration_types"


def test_integration_contract_and_catalog_remain_provider_neutral_and_reuse_registries() -> None:
    forbidden = {
        "importlib.metadata",
        "onlyalpha_plugin_binance",
        "onlyalpha_plugin_miniqmt",
        "onlyalpha_plugin_tushare",
    }

    for path in (CORE_CONTRACT, CATALOG):
        assert not (imported_modules_for_path(path, ROOT) & forbidden), path
    imports = imported_modules_for_path(CATALOG, ROOT)
    assert "onlyalpha.data.factory" in imports
    assert "onlyalpha.broker.factory" in imports


def test_integration_http_depends_on_application_contract_not_concrete_plugins() -> None:
    forbidden = {"onlyalpha_plugin_binance", "onlyalpha_plugin_miniqmt", "onlyalpha_plugin_tushare"}

    for path in HTTP_ROOT.rglob("*.py"):
        assert not (imported_modules_for_path(path, ROOT) & forbidden), path


def test_integration_l1_adds_no_environment_or_database_authority() -> None:
    scoped = (CORE_CONTRACT, CATALOG, *HTTP_ROOT.rglob("*.py"))
    forbidden = ("os.getenv", "os.environ", "product_credential", "integration_revision", "integration_draft")

    for path in scoped:
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path


def test_agent_provider_category_does_not_expand_data_source_broker_plugin_taxonomy() -> None:
    assert {item.value for item in OnlyIntegrationCategory} == {"DATA_SOURCE", "BROKER", "AGENT_PROVIDER"}
    assert {item.value for item in OnlyPluginType} == {"DATA_SOURCE", "BROKER"}
