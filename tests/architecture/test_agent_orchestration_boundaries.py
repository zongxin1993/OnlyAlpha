from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]

_AGENT_WORKFLOW_STDLIB_IMPORTS = {
    "__future__",
    "collections.abc",
    "contextlib",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "fcntl",
    "hashlib",
    "http.client",
    "importlib",
    "json",
    "os",
    "pathlib",
    "re",
    "socket",
    "ssl",
    "shutil",
    "types",
    "typing",
    "urllib.parse",
    "uuid",
}
_AGENT_WORKFLOW_VERIFIED_PUBLIC_BOUNDARIES = {
    "onlyalpha.application.search_product",
    "onlyalpha.research.run",
}


def _type_checking_import_ids(tree: ast.AST) -> set[int]:
    return {
        id(import_node)
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id in {"TYPE_CHECKING", "_TYPE_CHECKING"}
        for statement in node.body
        for import_node in ast.walk(statement)
        if isinstance(import_node, (ast.Import, ast.ImportFrom))
    }


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


def test_agent_application_has_no_generic_call_or_mutable_progress_authority() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "onlyalpha" / "research" / "agent"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for forbidden in (
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
        "session.status",
        "session.current_step",
        "session.next_action",
    ):
        assert forbidden not in source


def test_agent_driver_is_one_step_dispatch_without_second_progress_authority_or_io_bypass() -> None:
    orchestrator = ROOT / "packages" / "onlyalpha-agent-orchestrator" / "src" / "onlyalpha_agent_orchestrator"
    driver = orchestrator / "driver.py"
    source = driver.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(driver))
    advance = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "advance_once")
    assert not any(isinstance(node, (ast.While, ast.For, ast.AsyncFor)) for node in ast.walk(advance))
    assert ".invoke(" not in source
    assert "OnlyAgentSessionReducerV1" in source
    assert "execute_after_runtime_admission" in source
    assert "execute_external_model_occurrence" in source
    assert "execute_external_tool_occurrence" in source
    for forbidden in (
        "session.status",
        "session.current_step",
        "workflow_cursor",
        "driver_checkpoint",
        "pending_action",
        "retry manager",
        "requests.",
        "httpx.",
    ):
        assert forbidden not in source


def test_c_model_binding_excludes_operational_configuration_and_first_allowed_selection() -> None:
    orchestrator = ROOT / "packages" / "onlyalpha-agent-orchestrator" / "src" / "onlyalpha_agent_orchestrator"
    binding_source = (orchestrator / "bindings.py").read_text(encoding="utf-8")
    materialization_source = (orchestrator / "materialization.py").read_text(encoding="utf-8")
    binding_module = ast.parse(binding_source)
    binding_class = next(
        node
        for node in binding_module.body
        if isinstance(node, ast.ClassDef) and node.name == "OnlyAgentModelInvocationBindingV1"
    )
    annotated = {
        node.target.id
        for node in binding_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert not annotated.intersection(
        {"api_key", "token", "credential", "base_url", "proxy", "timeout", "tls", "ca_bundle_path"}
    )
    assert "allowed_prompt_template_fingerprints[0]" not in materialization_source
    assert "allowed_structured_output_schema_fingerprints[0]" not in materialization_source
    assert "allowed_model_execution_policy_fingerprints[0]" not in materialization_source
    assert "expected_model_id" not in materialization_source
    assert "DEFAULT_MODEL" not in materialization_source


def test_c_meaning_bearing_files_are_in_workflow_closure() -> None:
    from onlyalpha_agent_orchestrator.closure import ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1

    closed = {item.relative_name for item in ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1}
    assert {"bindings.py", "coordination.py", "driver.py", "materialization.py"}.issubset(closed)
    materialization = (
        ROOT
        / "packages"
        / "onlyalpha-agent-orchestrator"
        / "src"
        / "onlyalpha_agent_orchestrator"
        / "materialization.py"
    ).read_text(encoding="utf-8")
    assert "recovery_class" not in materialization
    assert "http_path" not in materialization
    assert "http_method" not in materialization


def test_decision_and_launch_store_commits_are_application_service_only() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "onlyalpha"
    allowed = {"research/agent/application.py"}
    for method in (".commit_decision(", ".commit_launch_record("):
        callsites = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if path.name != "decision_store.py" and method in path.read_text(encoding="utf-8")
        }
        assert callsites == allowed

    import onlyalpha.research.agent as agent_api

    assert "OnlyJsonAgentDecisionStore" not in agent_api.__all__
    assert "OnlyJsonAgentExperimentLaunchStore" not in agent_api.__all__


def test_agent_decision_and_launch_do_not_leak_into_search_identity() -> None:
    search_root = Path(__file__).resolve().parents[2] / "src" / "onlyalpha" / "research" / "search"
    source = "\n".join(path.read_text(encoding="utf-8") for path in search_root.rglob("*.py"))
    for forbidden in (
        "agent_decision_fingerprint",
        "agent_session_fingerprint",
        "tool_call_result_fingerprint",
        "experiment_launch_record_fingerprint",
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


def test_agent_reducer_and_evidence_do_not_duplicate_owning_authorities() -> None:
    from onlyalpha.research.agent import OnlyAgentEvidenceObservationV1

    root = Path(__file__).resolve().parents[2] / "src" / "onlyalpha" / "research" / "agent"
    reducer = (root / "session_state.py").read_text(encoding="utf-8")
    application = (root / "application.py").read_text(encoding="utf-8")
    assert "_branch_tools" not in reducer
    assert "_reconstruct_historical_decision" not in application
    assert "class AgentSearchState" not in reducer
    assert "class AgentResearchRunState" not in reducer
    assert not set(OnlyAgentEvidenceObservationV1.__dataclass_fields__).intersection(
        {"ic", "rank_ic", "sharpe", "coverage_ratio", "correlation", "stability_score"}
    )


def test_historical_fact_verifiers_do_not_derive_inputs_from_the_current_session_suffix() -> None:
    from onlyalpha.research.agent.application import OnlyAgentDecisionApplicationServiceV1
    from onlyalpha.research.agent.occurrence_service import OnlyAgentToolOccurrenceServiceV1

    historical_methods = (
        OnlyAgentDecisionApplicationServiceV1.verify_historical_tool_intent,
        OnlyAgentDecisionApplicationServiceV1._verify_historical_decision,
        OnlyAgentToolOccurrenceServiceV1.load_plan_verified,
    )
    for method in historical_methods:
        source = inspect.getsource(method)
        assert "budget_consumed(" not in source
        assert "range(self._tools.budget_consumed" not in source

    signature = inspect.signature(OnlyAgentDecisionApplicationServiceV1.verify_historical_tool_intent)
    assert "tool_call_ordinal" in signature.parameters


def test_agent_orchestrator_component_dependency_and_authority_boundary() -> None:
    orchestrator = ROOT / "packages/onlyalpha-agent-orchestrator/src/onlyalpha_agent_orchestrator"
    forbidden_import_roots = {
        "psycopg",
        "sqlalchemy",
        "httpx",
        "requests",
        "openai",
        "anthropic",
        "subprocess",
        "onlyalpha.research.agent.store",
        "onlyalpha.research.agent.occurrence_store",
        "onlyalpha.research.agent.decision_store",
        "onlyalpha.research.search",
    }
    for path in orchestrator.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not {
            imported
            for imported in imports
            if any(imported == item or imported.startswith(item + ".") for item in forbidden_import_roots)
        }, path

    source = "\n".join(path.read_text(encoding="utf-8") for path in orchestrator.rglob("*.py"))
    for forbidden in (
        "session.status",
        "session.current_step",
        "session.next_action",
        "workflow_cursor",
        "runtime_resume_point",
        "last_successful_agent_step",
        "class OrchestratorManifest",
        "class AgentRuntimeHash",
        "importlib.reload",
        "sys.path",
        "retry(",
        "git rev-parse",
    ):
        assert forbidden not in source


def test_core_does_not_import_agent_orchestrator_component() -> None:
    for path in (ROOT / "src/onlyalpha").rglob("*.py"):
        assert "onlyalpha_agent_orchestrator" not in path.read_text(encoding="utf-8"), path


def test_research_run_identity_does_not_depend_on_agent_or_gain_a_synthetic_sha_authority() -> None:
    run_root = ROOT / "src/onlyalpha/research/run"
    production_roots = (ROOT / "src/onlyalpha", ROOT / "packages")
    for path in run_root.rglob("*.py"):
        assert "onlyalpha.research.agent" not in path.read_text(encoding="utf-8"), path

    forbidden_definitions = {
        "ResearchRunFingerprint",
        "ResearchRunShaIdentity",
        "UUIDToFingerprint",
        "AgentReferenceMapping",
        "ReferenceTranslationStore",
    }
    defined: set[str] = set()
    for root in production_roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            defined.update(
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            )
    assert not forbidden_definitions.intersection(defined)


def test_agent_workflow_direct_semantic_dependencies_are_closed_or_explicit_boundaries() -> None:
    """A new direct semantic import cannot silently escape the reviewed closure."""

    from onlyalpha_agent_orchestrator.closure import ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1

    closed_modules = {
        item.package
        if item.relative_name == "__init__.py"
        else f"{item.package}.{item.relative_name.removesuffix('.py')}"
        for item in ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1
    }
    for item in ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1:
        path = (
            ROOT / "packages/onlyalpha-agent-orchestrator/src" / item.package.replace(".", "/") / item.relative_name
            if item.package == "onlyalpha_agent_orchestrator"
            or item.package.startswith("onlyalpha_agent_orchestrator.")
            else ROOT / "src" / item.package.replace(".", "/") / item.relative_name
        )
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        type_checking_import_ids = _type_checking_import_ids(tree)
        for node in ast.walk(tree):
            if id(node) in type_checking_import_ids:
                continue
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parent = item.package.split(".")
                    base = parent[: len(parent) - node.level + 1]
                    imported = {".".join((*base, *(node.module or "").split("."))).rstrip(".")}
                else:
                    imported = {node.module or ""}
            else:
                continue
            assert all(
                dependency in closed_modules
                or dependency in _AGENT_WORKFLOW_STDLIB_IMPORTS
                or dependency in _AGENT_WORKFLOW_VERIFIED_PUBLIC_BOUNDARIES
                for dependency in imported
            ), (path, imported)


def test_agent_semantic_modules_do_not_import_search_types_through_package_reexports() -> None:
    agent_root = ROOT / "src/onlyalpha/research/agent"
    for relative_name in ("application.py", "model.py", "semantic_translation.py"):
        source = (agent_root / relative_name).read_text(encoding="utf-8")
        assert "from onlyalpha.research.experiment import" not in source
        assert "from onlyalpha.research.experiment.model import" in source


def test_every_executed_workflow_package_initializer_is_explicitly_closed() -> None:
    from onlyalpha_agent_orchestrator.closure import ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1

    identities = {item.logical_resource_identity for item in ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1}
    assert {
        "onlyalpha.__init__.py",
        "onlyalpha.application.__init__.py",
        "onlyalpha.research.__init__.py",
        "onlyalpha.research.agent.__init__.py",
        "onlyalpha.research.experiment.__init__.py",
        "onlyalpha.agent.orchestrator.__init__.py",
    } <= identities


def test_workflow_package_initializers_have_explicit_execution_classifications() -> None:
    classifications = {
        "src/onlyalpha/__init__.py": "LAZY / INERT",
        "src/onlyalpha/research/__init__.py": "LAZY / INERT",
        "src/onlyalpha/research/experiment/__init__.py": "LAZY / INERT",
        "src/onlyalpha/research/agent/__init__.py": "CLOSED EAGER",
        "src/onlyalpha/application/__init__.py": "LAZY / INERT",
        "packages/onlyalpha-agent-orchestrator/src/onlyalpha_agent_orchestrator/__init__.py": "CLOSED EAGER",
    }
    assert set(classifications.values()) <= {"LAZY / INERT", "CLOSED EAGER", "FORMAL AUTHORITY BOUNDARY"}
    assert all((ROOT / relative).is_file() for relative in classifications)
    for relative, classification in classifications.items():
        if classification != "LAZY / INERT":
            continue
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        type_checking_import_ids = _type_checking_import_ids(tree)
        eager_onlyalpha_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import) and id(node) not in type_checking_import_ids
            for alias in node.names
            if alias.name == "onlyalpha" or alias.name.startswith("onlyalpha.")
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and id(node) not in type_checking_import_ids
            and (node.module == "onlyalpha" or (node.module or "").startswith("onlyalpha."))
        }
        assert not eager_onlyalpha_imports, relative


def test_closed_workflow_semantics_forbid_unreviewed_dynamic_imports() -> None:
    from onlyalpha_agent_orchestrator.closure import ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1

    lazy_initializers = {
        "onlyalpha.__init__.py",
        "onlyalpha.application.__init__.py",
        "onlyalpha.research.__init__.py",
        "onlyalpha.research.experiment.__init__.py",
    }
    for item in ONLY_AGENT_WORKFLOW_RESOURCE_CLOSURE_V1:
        if item.logical_resource_identity in lazy_initializers:
            continue
        path = (
            ROOT / "packages/onlyalpha-agent-orchestrator/src" / item.package.replace(".", "/") / item.relative_name
            if item.package == "onlyalpha_agent_orchestrator"
            or item.package.startswith("onlyalpha_agent_orchestrator.")
            else ROOT / "src" / item.package.replace(".", "/") / item.relative_name
        )
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not calls.intersection({"__import__", "import_module"}), path


def test_runtime_execution_permit_has_one_mint_authority_and_no_external_seal_reference() -> None:
    orchestrator = ROOT / "packages/onlyalpha-agent-orchestrator/src/onlyalpha_agent_orchestrator"
    constructor_calls: set[tuple[str, str]] = set()
    mint_calls: set[tuple[str, str]] = set()
    seal_files: set[str] = set()
    for path in orchestrator.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                enclosing = next(
                    (
                        parent.name
                        for parent in ast.walk(tree)
                        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) and node in ast.walk(parent)
                    ),
                    "<module>",
                )
                if node.func.id == "OnlyAgentRuntimeExecutionPermit":
                    constructor_calls.add((path.name, enclosing))
                elif node.func.id == "_mint_runtime_execution_permit":
                    mint_calls.add((path.name, enclosing))
        if "_ADMISSION_SEAL" in source:
            seal_files.add(path.name)
    assert constructor_calls == {("runtime.py", "_mint_runtime_execution_permit")}
    assert mint_calls == {("runtime.py", "execute_after_runtime_admission")}
    assert seal_files == {"runtime.py"}


def test_future_external_execution_seam_requires_runtime_execution_permit() -> None:
    source = (ROOT / "packages/onlyalpha-agent-orchestrator/src/onlyalpha_agent_orchestrator/runtime.py").read_text(
        encoding="utf-8"
    )
    assert "continuation: Callable[[OnlyAgentRuntimeExecutionPermit], ResultT]" in source
    assert "def assert_runtime_execution_permit(" in source
    assert "Callable[[OnlyAgentAdmittedRuntimeV1]" not in source


def test_external_io_permit_is_minted_only_after_prepared_execution_validation() -> None:
    orchestrator = ROOT / "packages/onlyalpha-agent-orchestrator/src/onlyalpha_agent_orchestrator"
    constructor_calls: set[tuple[str, str]] = set()
    mint_calls: set[tuple[str, str]] = set()
    send_calls: set[str] = set()
    adapter_invoke_calls: set[str] = set()
    for path in orchestrator.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for node in ast.walk(function):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name):
                    if node.func.id == "OnlyAgentExternalIoPermit":
                        constructor_calls.add((path.name, function.name))
                    elif node.func.id == "_mint_external_io_permit":
                        mint_calls.add((path.name, function.name))
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr == "send":
                        send_calls.add(path.relative_to(orchestrator).as_posix())
                    elif node.func.attr == "invoke":
                        adapter_invoke_calls.add(path.relative_to(orchestrator).as_posix())
    assert constructor_calls == {("runtime.py", "_mint_external_io_permit")}
    assert mint_calls == {
        ("execution.py", "execute_external_model_occurrence"),
        ("execution.py", "execute_external_tool_occurrence"),
        ("execution.py", "invoke"),
    }
    assert send_calls == {
        "adapters/openai_compatible.py",
        "adapters/product_api.py",
    }
    assert adapter_invoke_calls == {"execution.py"}


def test_search_http_projection_is_transport_only_and_search_semantics_do_not_reverse_depend() -> None:
    search_core = ROOT / "src/onlyalpha/research/search"
    for path in search_core.rglob("*.py"):
        assert "onlyalpha_http_server" not in path.read_text(encoding="utf-8"), path

    search_http = ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server/search"
    source = "\n".join(path.read_text(encoding="utf-8") for path in search_http.rglob("*.py"))
    assert "OnlyResearchProductBoundary" in source
    for forbidden in (
        "onlyalpha.persistence",
        "OnlyPostgres",
        "psycopg",
        "sqlalchemy",
        "DIRECT_DATABASE",
        "onlyalpha.broker",
        "onlyalpha.runtime.live",
    ):
        assert forbidden not in source
