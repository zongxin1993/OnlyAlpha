from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlyParameterExpectedStateV1,
    OnlySubmitParameterSearchExperimentV1,
    OnlySubmitSymbolicSearchExperimentV1,
    OnlySymbolicExpectedStateV1,
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_transport_neutral_search_product_has_no_http_agent_or_concrete_persistence_dependency() -> None:
    imports = _imports(Path("src/onlyalpha/application/search_product.py"))
    forbidden = ("fastapi", "onlyalpha_http_server", "onlyalpha.research.agent", "psycopg")
    assert not any(name.startswith(forbidden) for name in imports)


def test_search_product_commands_cannot_carry_agent_or_transport_identity() -> None:
    for model in (
        OnlySubmitSymbolicSearchExperimentV1,
        OnlySubmitParameterSearchExperimentV1,
        OnlyAdvanceSearchExperimentV1,
    ):
        names = {item.name for item in fields(model)}
        assert not names & {
            "agent_session_fingerprint",
            "model_call_fingerprint",
            "tool_call_fingerprint",
            "http_idempotency_key",
            "url",
            "headers",
        }


def test_expected_state_is_method_specific_and_has_no_generic_transition_version() -> None:
    assert OnlySymbolicExpectedStateV1 is not OnlyParameterExpectedStateV1
    for model in (OnlySymbolicExpectedStateV1, OnlyParameterExpectedStateV1):
        assert "search_version" not in {item.name for item in fields(model)}


def test_search_method_adapters_use_authority_apis_not_direct_file_or_sql_writes() -> None:
    paths = (
        Path("src/onlyalpha/research/search/symbolic/product.py"),
        Path("src/onlyalpha/research/search/parameter/product.py"),
    )
    forbidden_calls = {"open", "write_text", "write_bytes", "execute", "executemany"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        assert not called & forbidden_calls, path


def test_search_stores_have_no_product_command_retry_index() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            Path("src/onlyalpha/research/experiment/store.py"),
            Path("src/onlyalpha/research/search/symbolic/store.py"),
            Path("src/onlyalpha/research/search/parameter/store.py"),
        )
    )
    assert "ProductCommandId" not in source
    assert "product_command_id" not in source.lower()
