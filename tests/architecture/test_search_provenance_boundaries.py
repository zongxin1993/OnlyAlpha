from __future__ import annotations

import ast
from pathlib import Path


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
