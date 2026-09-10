from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def test_agent_context_core_has_no_provider_transport_execution_or_provenance_discovery_dependencies() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "onlyalpha" / "research" / "agent"
    forbidden_import_roots = {
        "anthropic",
        "httpx",
        "openai",
        "psycopg",
        "requests",
        "subprocess",
        "onlyalpha.broker",
        "onlyalpha.execution",
        "onlyalpha.live",
        "onlyalpha_http_server",
    }
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not {
            imported
            for imported in imports
            if any(imported == item or imported.startswith(item + ".") for item in forbidden_import_roots)
        }, path
        source = path.read_text(encoding="utf-8")
        assert "git rev-parse" not in source
        assert "ONLYALPHA_BUILD_SOURCE_REVISION" not in source
        assert "packages/onlyalpha-agent-orchestrator" not in source


def test_agent_occurrence_foundation_has_no_next_action_or_generic_call_authority() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "onlyalpha" / "research" / "agent"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for forbidden in (
        "class OnlyAgentDecisionV1",
        "class GenericCallPlan",
        "class GenericCallResult",
        "class GenericExternalCallStore",
        "model_call.status",
        "tool_call.status",
        "session.model_calls_used",
        "session.tool_calls_used",
        "SearchRouter",
        "httpx.Client",
        "requests.Session",
        "retry_authorized=True",
        "TEST_MODEL_RETRY_AUTHORIZED",
        "class OnlyAgentModelRetryAuthorization",
        "load_model_retry_authorization_verified",
    ):
        assert forbidden not in source


def test_agent_occurrence_foundation_exposes_no_retry_pseudo_authority_or_bypass() -> None:
    import onlyalpha.research.agent as agent

    forbidden_public_names = (
        "OnlyAgentModelRetryAuthorizationKind",
        "OnlyAgentModelRetryAuthorizationV1",
        "OnlyAgentModelRetryAuthorizationReader",
    )
    assert not any(hasattr(agent, name) for name in forbidden_public_names)

    root = Path(__file__).resolve().parents[2] / "src" / "onlyalpha" / "research" / "agent"
    forbidden_parameters = {
        "authorized",
        "retry_authorized",
        "retry_authorization_fingerprint",
        "human_authorization_fingerprint",
    }
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parameters = {
            argument.arg
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        }
        assert not parameters.intersection(forbidden_parameters), path


def test_model_and_tool_occurrences_remain_distinct_public_authorities() -> None:
    from onlyalpha.research.agent import (
        OnlyAgentModelCallPlanV1,
        OnlyAgentModelCallResultV1,
        OnlyAgentToolCallPlanV1,
        OnlyAgentToolCallResultV1,
    )

    assert (
        len({OnlyAgentModelCallPlanV1, OnlyAgentModelCallResultV1, OnlyAgentToolCallPlanV1, OnlyAgentToolCallResultV1})
        == 4
    )
    assert "product_api_contract_fingerprint" not in OnlyAgentModelCallPlanV1.__dataclass_fields__
    assert "model_id" not in OnlyAgentToolCallPlanV1.__dataclass_fields__
    assert set(OnlyAgentModelCallPlanV1.__dataclass_fields__) == {
        "schema_version",
        "agent_session_fingerprint",
        "call_ordinal",
        "logical_role",
        "role_policy_fingerprint",
        "provider_id",
        "model_id",
        "model_version",
        "prompt_template_fingerprint",
        "structured_output_schema_fingerprint",
        "tool_policy_fingerprint",
        "model_execution_policy_fingerprint",
        "response_affecting_settings",
        "ordered_context_references",
        "parent_agent_decision_fingerprint",
        "retry_of_plan_fingerprint",
        "model_call_plan_fingerprint",
    }
    assert set(OnlyAgentToolCallPlanV1.__dataclass_fields__) == {
        "schema_version",
        "agent_session_fingerprint",
        "tool_call_ordinal",
        "authorizing_agent_decision_fingerprint",
        "tool_class",
        "product_api_major",
        "product_api_contract_fingerprint",
        "operation_identity",
        "canonical_validated_request",
        "canonical_request_fingerprint",
        "exact_identity_inputs",
        "product_command_id_or_idempotency_key",
        "tool_policy_fingerprint",
        "tool_call_plan_fingerprint",
    }
    assert "recovery_class" not in OnlyAgentToolCallPlanV1.__dataclass_fields__


def test_occurrence_store_commit_boundary_is_not_reexported_or_bypassed_in_production() -> None:
    import onlyalpha.research.agent as agent

    assert not hasattr(agent, "OnlyJsonAgentModelOccurrenceStore")
    assert not hasattr(agent, "OnlyJsonAgentToolOccurrenceStore")
    root = Path(__file__).resolve().parents[2] / "src" / "onlyalpha"
    for method in (".commit_plan(", ".commit_result("):
        callsites = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if path.name != "occurrence_store.py" and method in path.read_text(encoding="utf-8")
        }
        assert callsites == {"research/agent/occurrence_service.py"}


def test_agent_session_contract_has_no_mutable_status_or_runtime_occurrence_fields() -> None:
    from onlyalpha.research.agent import OnlyAgentSessionManifestV1

    fields = set(OnlyAgentSessionManifestV1.__dataclass_fields__)
    assert not fields.intersection(
        {
            "status",
            "current_step",
            "progress",
            "current_role",
            "next_action",
            "updated_at",
            "model_call_plan",
            "tool_call_plan",
            "agent_decision",
        }
    )


def test_agent_workflow_manifest_derivation_has_no_provenance_override() -> None:
    from onlyalpha.research.agent import derive_agent_workflow_implementation_manifest

    parameters = set(inspect.signature(derive_agent_workflow_implementation_manifest).parameters)
    assert parameters == {"workflow_id", "workflow_semantic_version", "runtime_resources"}
    assert not parameters.intersection({"build_provenance", "source_revision", "distribution_provenance"})
