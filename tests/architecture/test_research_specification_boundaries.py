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
        "onlyalpha.research.definition",
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


def test_scientific_evidence_introduces_no_parallel_authority_or_registry() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha/research").rglob("*.py"))
    forbidden = (
        "ScientificEvidenceStore",
        "CandidateStore",
        "SignalStore",
        "GraphStore",
        "PredicateResultStore",
        "PredicateRuntime",
        "PredicateRegistry",
    )
    assert not any(name in source for name in forbidden)


def test_predicate_primitives_are_owned_by_research_calculation() -> None:
    predicate = Path("src/onlyalpha/research/calculation/predicate.py")
    assert predicate.is_file()
    source = predicate.read_text(encoding="utf-8")
    assert "only_register_research_predicate_primitives" in source
    runtime = Path("src/onlyalpha/runtime/research/factory.py").read_text(encoding="utf-8")
    assert "onlyalpha.research.definition.primitives" not in runtime
