from __future__ import annotations

import ast
from pathlib import Path


def test_research_specification_is_core_only_and_has_no_operational_or_trading_dependencies() -> None:
    root = Path("src/onlyalpha/research/specification")
    forbidden = (
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "onlyalpha.web",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.account",
    )
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports.extend(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_graph_template_materialization_has_one_implementation() -> None:
    source = Path("src/onlyalpha/research")
    definitions = []
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text())
        definitions.extend(
            (path, node.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "OnlyResearchGraphTemplateMaterializer"
        )
    assert definitions == [
        (Path("src/onlyalpha/research/sweep/materialization.py"), "OnlyResearchGraphTemplateMaterializer")
    ]
