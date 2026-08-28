from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
CLIENT = ROOT / "packages/client/onlyalpha-client"
CLIENT_SOURCE = CLIENT / "src/onlyalpha_client"
CONTRACT_PATH = ROOT / "docs/architecture/p9_k6_external_client_contract.toml"
ALLOWED_CLASSIFICATIONS = {
    "CLOSED",
    "INTERNAL",
    "LEGACY_K8_TARGET",
    "OPERATOR / INFRASTRUCTURE",
    "PRODUCT",
    "PRODUCT_API_CLIENT",
    "PRODUCT_CONTROL_PLANE",
    "READ_ONLY_COMPATIBILITY_SURFACE",
    "TEST / SCENARIO",
}


def _contract() -> dict[str, object]:
    return tomllib.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
    return result


def _is_core_or_api(imported: str) -> bool:
    return imported == "onlyalpha" or imported.startswith(("onlyalpha.", "onlyalpha_api"))


def test_onlyalpha_client_package_has_no_core_dependency_or_import() -> None:
    metadata = tomllib.loads((CLIENT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = metadata["project"]["dependencies"]
    assert all(not dependency.lower().startswith("onlyalpha") for dependency in dependencies)
    for path in sorted(CLIENT_SOURCE.rglob("*.py")):
        assert all(not _is_core_or_api(imported) for imported in _imports(path)), path


def test_generated_python_client_is_fresh() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/openapi_clients.py", "check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_product_client_and_cli_have_no_local_fallback_capability() -> None:
    forbidden_imports = (
        "onlyalpha.engine",
        "onlyalpha.runtime",
        "onlyalpha.kernel",
        "onlyalpha.application",
        "onlyalpha.persistence",
        "onlyalpha.strategy",
    )
    forbidden_symbols = (
        "OnlyEngine",
        "OnlyRuntime",
        "OnlyResearchCommandService",
        "OnlyPostgres",
        "only_default_engine_services",
    )
    for path in sorted(CLIENT_SOURCE.rglob("*.py")):
        imports = _imports(path)
        assert all(not imported.startswith(forbidden_imports) for imported in imports), path
        if "generated" not in path.parts:
            source = path.read_text(encoding="utf-8")
            assert all(symbol not in source for symbol in forbidden_symbols), path


def test_web_remains_bound_to_canonical_generated_contract_without_kernel_imports() -> None:
    package = (ROOT / "apps/onlyalpha-web/package.json").read_text(encoding="utf-8")
    web_suite = (ROOT / "scripts/web_suite.py").read_text(encoding="utf-8")
    assert package.count("../../contracts/research-api/v2/openapi.json") == 1
    assert "check_generated_client" in web_suite
    for path in sorted((ROOT / "apps/onlyalpha-web/src").rglob("*")):
        if path.suffix in {".ts", ".tsx"}:
            source = path.read_text(encoding="utf-8")
            assert "OnlyEngine" not in source
            assert "onlyalpha.kernel" not in source


def test_product_examples_cannot_construct_engine_or_runtime() -> None:
    product_roots = _contract()["product_example_roots"]
    assert isinstance(product_roots, list) and product_roots
    forbidden = {"OnlyEngine", "OnlyRuntime", "OnlyBacktestRuntime", "OnlyResearchRuntime", "OnlyLiveRuntime"}
    for relative in product_roots:
        root = ROOT / str(relative)
        assert root.is_dir()
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            assert not names.intersection(forbidden), path
            assert all(not _is_core_or_api(imported) for imported in _imports(path)), path


def test_operator_direct_access_is_an_exact_narrow_allowlist() -> None:
    allowlist = _contract()["operator_direct_access_allowlist"]
    assert allowlist == [
        "scripts/database.py",
        "src/onlyalpha/cli.py:operations",
        "src/onlyalpha/research/worker_main.py",
        "packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/doctor.py",
        "packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare/doctor.py",
    ]


def test_artifact_http_executable_is_read_only_compatibility_surface() -> None:
    artifact = _contract()["artifact_http"]
    assert artifact == {
        "entrypoint": "onlyalpha-artifact-api",
        "decision": "READ_ONLY_COMPATIBILITY_SURFACE",
        "mutation_capability": False,
        "removal_owner": "P9.K.8",
        "closure": "REMOVED",
    }
    app = (ROOT / "packages/api/onlyalpha-api/src/onlyalpha_api/app.py").read_text(encoding="utf-8")
    metadata = tomllib.loads((ROOT / "packages/api/onlyalpha-api/pyproject.toml").read_text(encoding="utf-8"))
    assert "onlyalpha-artifact-api" not in metadata["project"]["scripts"]
    assert not (ROOT / "packages/api/onlyalpha-api/src/onlyalpha_api/artifact_main.py").exists()
    assert "create_artifact_query_app" not in app
    assert "create_artifact_router(artifact_service)" in app


def test_external_actor_and_cli_classification_is_complete() -> None:
    contract = _contract()
    surfaces = contract["external_surfaces"]
    commands = contract["cli_commands"]
    documentation = contract["documentation"]
    assert isinstance(surfaces, list) and isinstance(commands, list) and isinstance(documentation, list)
    assert len({item["id"] for item in surfaces}) == len(surfaces)
    assert len({item["command"] for item in commands}) == len(commands)
    assert len({item["path"] for item in documentation}) == len(documentation)
    for item in (*surfaces, *commands, *documentation):
        assert item["classification"] in ALLOWED_CLASSIFICATIONS
        assert item["classification"] not in {"UNKNOWN", "UNCLASSIFIED"}
        assert item["action"]


def test_root_product_cli_commands_are_closed_without_api_or_local_fallbacks() -> None:
    root_cli = (ROOT / "src/onlyalpha/cli.py").read_text(encoding="utf-8")
    assert "OnlyAlphaClient" not in root_cli
    command_contract = {
        item["command"]: item["classification"]
        for item in _contract()["cli_commands"]  # type: ignore[index]
    }
    assert command_contract["onlyalpha run"] == "CLOSED"
    assert command_contract["onlyalpha snapshot"] == "CLOSED"
    assert command_contract["onlyalpha operations status"] == "OPERATOR / INFRASTRUCTURE"
    assert command_contract["onlyalpha scenario run"] == "TEST / SCENARIO"
    assert not any(item["classification"] == "LEGACY_K8_TARGET" for item in _contract()["external_surfaces"])
    assert not any(item["k8_debt"] for item in _contract()["external_surfaces"])
