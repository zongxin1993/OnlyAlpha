"""Permanent Product-surface retirement and runtime-admission guards."""

from __future__ import annotations

import ast
import subprocess
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
PRODUCT_ROOTS = (ROOT / "src", ROOT / "packages", ROOT / "apps")


def _imports(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
    return frozenset(result)


def _console_entry_points() -> dict[str, str]:
    result: dict[str, str] = {}
    listed = subprocess.run(
        ["git", "ls-files", "*pyproject.toml"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    for relative in listed.stdout.splitlines():
        path = ROOT / relative
        if not path.is_file():
            continue
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        scripts = document.get("project", {}).get("scripts", {})
        assert isinstance(scripts, dict)
        for name, target in scripts.items():
            assert name not in result, name
            result[name] = str(target)
    return result


def test_retired_repository_and_product_surfaces_are_absent() -> None:
    assert not (ROOT / "prompts").exists()
    assert not (ROOT / "examples").exists()
    assert not (ROOT / "packages/client/onlyalpha-client").exists()
    assert not (ROOT / "src/onlyalpha/cli.py").exists()
    assert not (ROOT / "scripts/openapi_clients.py").exists()


def test_only_process_and_provider_entrypoints_remain() -> None:
    entry_points = _console_entry_points()
    assert "onlyalpha" not in entry_points
    assert "onlyalpha-client" not in entry_points
    assert entry_points["onlyalpha-http-server"] == "onlyalpha_http_server.main:main"
    assert entry_points["onlyalpha-research-worker"] == "onlyalpha.research.worker_main:main"
    assert entry_points["onlyalpha-miniqmt"] == "onlyalpha_plugin_miniqmt.doctor:main"
    assert entry_points["onlyalpha-tushare"] == "onlyalpha_plugin_tushare.doctor:main"


def test_scenario_semantics_are_verification_only() -> None:
    scenario_root = ROOT / "src/onlyalpha/scenario"
    assert (scenario_root / "parser.py").is_file()
    assert (scenario_root / "runner.py").is_file()
    assert (scenario_root / "assertions.py").is_file()
    defaults = (ROOT / "src/onlyalpha/runtime/defaults.py").read_text(encoding="utf-8")
    assert "Scenario" not in defaults
    for root in PRODUCT_ROOTS:
        for path in root.rglob("*.py"):
            if scenario_root in path.parents:
                continue
            assert not any(
                name == "onlyalpha.scenario" or name.startswith("onlyalpha.scenario.") for name in _imports(path)
            ), path


def test_product_runtime_cannot_be_admitted_from_a_file() -> None:
    engine = (ROOT / "src/onlyalpha/engine/engine.py").read_text(encoding="utf-8")
    assert "add_cluster_from_file" not in engine
    assert "OnlyClusterRunConfig.load(" not in engine
    for root in PRODUCT_ROOTS:
        for path in root.rglob("*.py"):
            if path == ROOT / "src/onlyalpha/config/cluster_document.py":
                continue
            source = path.read_text(encoding="utf-8")
            assert "OnlyClusterRunConfig.load(" not in source, path
    for path in (ROOT / "packages/onlyalpha-http-server/src").rglob("*.py"):
        imports = _imports(path)
        assert not any(name == "onlyalpha.config" or name.startswith("onlyalpha.config.") for name in imports), path


def test_web_remains_the_governed_product_consumer() -> None:
    package = (ROOT / "packages/onlyalpha-web-console/package.json").read_text(encoding="utf-8")
    web_suite = (ROOT / "scripts/web_suite.py").read_text(encoding="utf-8")
    assert package.count("../../contracts/product-api/v2/openapi.json") == 1
    assert "check_generated_client" in web_suite
    for path in (ROOT / "packages/onlyalpha-web-console/src").rglob("*"):
        if path.suffix in {".ts", ".tsx"}:
            source = path.read_text(encoding="utf-8")
            assert "OnlyEngine" not in source
            assert "onlyalpha.kernel" not in source
