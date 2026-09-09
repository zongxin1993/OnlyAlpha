from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlyParameterExpectedStateV1,
    OnlySearchResearchRunReader,
    OnlySubmitParameterSearchExperimentV1,
    OnlySubmitParameterSearchExperimentV2,
    OnlySubmitSymbolicSearchExperimentV1,
    OnlySubmitSymbolicSearchExperimentV2,
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
        OnlySubmitSymbolicSearchExperimentV2,
        OnlySubmitParameterSearchExperimentV2,
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


def test_runtime_generation_is_product_v2_operational_intent_not_search_semantic_identity() -> None:
    assert "runtime_generation_fingerprint" not in {item.name for item in fields(OnlySubmitSymbolicSearchExperimentV1)}
    assert "runtime_generation_fingerprint" not in {item.name for item in fields(OnlySubmitParameterSearchExperimentV1)}
    assert "runtime_generation_fingerprint" in {item.name for item in fields(OnlySubmitSymbolicSearchExperimentV2)}
    assert "runtime_generation_fingerprint" in {item.name for item in fields(OnlySubmitParameterSearchExperimentV2)}
    source = Path("src/onlyalpha/research/experiment/model.py").read_text(encoding="utf-8")
    assert "runtime_generation_fingerprint" not in source


def test_search_runtime_binding_has_one_authority_and_no_host_or_transport_scope() -> None:
    application = Path("src/onlyalpha/application/search_product.py").read_text(encoding="utf-8")
    runtime = Path("src/onlyalpha/application/runtime_generation.py").read_text(encoding="utf-8")
    symbolic = Path("src/onlyalpha/research/search/symbolic/product.py").read_text(encoding="utf-8")
    parameter = Path("src/onlyalpha/research/search/parameter/integration.py").read_text(encoding="utf-8")
    assert "bind_work_exact" in application and "bind_work_exact" in runtime
    assert "bind_derived_work" in runtime
    assert "parent_runtime_work_id=" in symbolic
    assert "parent_runtime_work_id=" in parameter
    for forbidden in (
        "SearchExecutionBindingStore",
        "search_runtime_generation_map",
        "subprocess",
        "fastapi",
    ):
        assert forbidden not in application


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


def test_search_research_run_dereference_is_transport_neutral_and_exact() -> None:
    assert getattr(OnlySearchResearchRunReader, "_is_protocol", False)
    paths = (
        Path("src/onlyalpha/research/search/symbolic/product.py"),
        Path("src/onlyalpha/research/search/symbolic/controller.py"),
        Path("src/onlyalpha/research/search/parameter/product.py"),
    )
    imports = set().union(*(_imports(path) for path in paths))
    assert not any(name.startswith("onlyalpha.persistence.postgres") for name in imports)
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "only_load_search_research_run_exact" in source
    assert "expected_specification=" in source


def test_symbolic_enumeration_absence_does_not_catch_contextual_verification_failures() -> None:
    controller = Path("src/onlyalpha/research/search/symbolic/controller.py").read_text(encoding="utf-8")
    product = Path("src/onlyalpha/research/search/symbolic/product.py").read_text(encoding="utf-8")
    historical = Path("src/onlyalpha/research/search/symbolic/historical.py").read_text(encoding="utf-8")
    assert "_enumeration_absent" not in controller
    assert '"REFERENCE_INVALID"' not in controller
    assert '"REFERENCE_INVALID"' not in product
    assert 'exc.code == "SEARCH_ENUMERATION_RESULT_NOT_FOUND"' in historical


def test_generic_product_service_orchestrates_explicit_effect_assessment_only() -> None:
    source = Path("src/onlyalpha/application/search_product.py").read_text(encoding="utf-8")
    assert "assessment = adapter.assess_advance_effect(command)" in source
    assert "OnlySearchProductEffectStateV1.PARTIAL_EXACT_EFFECT" in source
    assert "adapter.verify_advance_effect(command)" in source
