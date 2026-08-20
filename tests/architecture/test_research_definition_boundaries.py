from __future__ import annotations

import ast
from pathlib import Path

import pytest

from onlyalpha.calculation import OnlyCalculationRegistry
from onlyalpha.research import only_register_research_predicate_primitives

pytestmark = pytest.mark.architecture


def test_research_definition_has_no_web_operational_trading_or_storage_authority() -> None:
    forbidden = (
        "fastapi",
        "pydantic",
        "graphviz",
        "onlyalpha.web",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.account",
        "onlyalpha.broker",
        "onlyalpha.research.run",
        "onlyalpha.research.artifact",
    )
    for path in Path("src/onlyalpha/research/definition").glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports.extend(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_predicate_reuses_calculation_authority_and_has_no_runtime_or_store() -> None:
    root = Path("src/onlyalpha/research/definition")
    classes = [
        node.name
        for path in root.glob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef)
    ]
    assert not any("Runtime" in name or "Store" in name or "Manager" in name for name in classes)


def test_internal_predicates_are_not_exposed_by_public_authoring_descriptors() -> None:
    registry = OnlyCalculationRegistry()
    only_register_research_predicate_primitives(registry)
    assert registry.type_definitions()
    assert registry.descriptors() == ()


def test_definition_http_is_projection_only_and_error_ownership_is_route_metadata() -> None:
    api = Path("packages/api/onlyalpha-api/src/onlyalpha_api")
    definition_source = "\n".join(
        (api / "research" / name).read_text(encoding="utf-8")
        for name in (
            "definition_routes.py",
            "definition_schema.py",
            "definition_service.py",
            "discovery.py",
        )
    )
    for forbidden in (
        "OnlyResearchCommandService",
        "OnlyResearchScheduler",
        "OnlyResearchWorkerService",
        "OnlyResearchRunStore",
        "OnlyEngine(",
        "DefinitionStore",
        "ResolutionStore",
    ):
        assert forbidden not in definition_source
    discovery = (api / "research" / "discovery.py").read_text(encoding="utf-8")
    assert "OnlyCalculationRegistry()" not in discovery
    app = (api / "app.py").read_text(encoding="utf-8")
    assert "request.url.path" not in app
    assert "_RESEARCH_RUN_PATH" not in app
