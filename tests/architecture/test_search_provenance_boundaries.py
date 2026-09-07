from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path
from typing import get_type_hints

from onlyalpha.research.search.symbolic import (
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicExternalSourceReferenceV1,
    OnlyVerifiedSymbolicProposalV1,
    materialize_symbolic_research_specification,
)


def test_search_provenance_has_no_forbidden_authority_dependencies() -> None:
    root = Path("src/onlyalpha/research/experiment")
    imported: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    forbidden_prefixes = (
        "onlyalpha.agent",
        "onlyalpha.web",
        "onlyalpha.research.evaluation.execution",
        "onlyalpha.strategy.qualification",
        "onlyalpha_http_server",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imported)


def test_search_provenance_contains_contract_not_search_or_agent_implementation() -> None:
    root = Path("src/onlyalpha/research/experiment")
    class_names: set[str] = set()
    function_names: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        class_names.update(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
        function_names.update(node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
    assert not any(name.endswith(("SearchAlgorithm", "SearchScheduler", "Agent")) for name in class_names)
    assert not {"search", "rank_candidates", "select_best_candidate", "call_model"} & function_names


def test_symbolic_search_closure_has_no_forbidden_authority_dependencies() -> None:
    root = Path("src/onlyalpha/research/search/symbolic")
    imported: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    forbidden = ("onlyalpha.agent", "onlyalpha.web", "onlyalpha.broker", "onlyalpha.runtime.live")
    assert not any(name.startswith(forbidden) for name in imported)


def test_intrinsic_store_cannot_masquerade_as_contextual_reader() -> None:
    methods = set(dir(OnlyJsonSymbolicSearchStore))
    assert "load_search_space_intrinsic_verified" in methods
    assert "load_proposal_intrinsic_verified" in methods
    assert "load_search_space_verified" not in methods
    assert "load_proposal_verified" not in methods


def test_terminal_is_reference_only_and_materialization_requires_verified_proposal() -> None:
    assert {item.name for item in fields(OnlySymbolicExternalSourceReferenceV1)} == {
        "source_id",
        "source_contract_fingerprint",
        "schema_version",
    }
    annotation = get_type_hints(materialize_symbolic_research_specification)["verified_proposal"]
    assert annotation is OnlyVerifiedSymbolicProposalV1
