from __future__ import annotations

import ast
from pathlib import Path

import pytest

from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.runtime.defaults import only_default_engine_services

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
SOURCE_ROOT = ROOT / "src" / "onlyalpha"
RUNTIME_ROOT = SOURCE_ROOT / "runtime"
LEGACY_PRODUCTS = ("PAPER", "SHADOW")


def test_runtime_product_taxonomy_is_exact() -> None:
    assert {mode.value for mode in OnlyRuntimeMode} == {"RESEARCH", "BACKTEST", "SIM", "LIVE"}


def test_legacy_runtime_product_packages_do_not_exist() -> None:
    assert not list((RUNTIME_ROOT / "paper").glob("*.py"))
    assert not list((RUNTIME_ROOT / "shadow").glob("*.py"))


def test_default_registry_contains_only_target_runtime_products() -> None:
    registry = only_default_engine_services().assembler._runtime_factories
    assert set(registry._factories) == {"RESEARCH", "BACKTEST", "SIM", "LIVE"}


def test_production_source_has_no_legacy_runtime_import_or_alias() -> None:
    violations: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imports = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        if any(name.startswith(("onlyalpha.runtime.paper", "onlyalpha.runtime.shadow")) for name in imports):
            violations.append(f"{path.relative_to(ROOT)}: legacy import")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names.intersection(LEGACY_PRODUCTS):
                violations.append(f"{path.relative_to(ROOT)}: legacy alias")
    assert violations == []


@pytest.mark.parametrize("legacy", LEGACY_PRODUCTS)
def test_default_registry_has_no_legacy_factory(legacy: str) -> None:
    registry = only_default_engine_services().assembler._runtime_factories
    with pytest.raises(ValueError, match="RUNTIME_FACTORY_NOT_AVAILABLE"):
        registry.require(legacy)
