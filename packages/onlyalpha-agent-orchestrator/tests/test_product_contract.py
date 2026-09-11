from __future__ import annotations

import copy
import json
import socket
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import pytest
from onlyalpha_agent_orchestrator.adapters.product_api import (
    OnlyContractDrivenProductApiAdapterV1,
    OnlyProductApiContractV2,
)
from onlyalpha_agent_orchestrator.adapters.transport import (
    OnlyHttpDispatchClassification,
    OnlyRawHttpTransportV1,
)
from onlyalpha_agent_orchestrator.config import OnlyProductApiEndpointConfigV1
from onlyalpha_agent_orchestrator.runtime import (
    _mint_external_io_permit,
    _mint_runtime_execution_permit,
)

from onlyalpha.research.agent.errors import OnlyAgentContextError
from onlyalpha.research.agent.model import OnlyAgentToolClass
from onlyalpha.research.agent.occurrence import (
    OnlyAgentContextReferenceV1,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolRecoveryClass,
)

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "contracts/product-api/v2/openapi.json"
EXTENSION = "x-onlyalpha-agent-operation"


def _document() -> dict[str, object]:
    value = json.loads(CONTRACT.read_bytes())
    assert isinstance(value, dict)
    return value


def _operations(document: dict[str, object]):  # type: ignore[no-untyped-def]
    paths = document["paths"]
    assert isinstance(paths, dict)
    for path, path_item in paths.items():
        assert isinstance(path_item, dict)
        for method, operation in path_item.items():
            if method in {"delete", "get", "patch", "post", "put"} and isinstance(operation, dict):
                yield path, method, operation


def _agent_operation(document: dict[str, object], tool_class: str):  # type: ignore[no-untyped-def]
    matches = [
        operation
        for _, _, operation in _operations(document)
        if operation.get(EXTENSION, {}).get("tool_class") == tool_class
    ]
    assert matches
    return matches[0]


def _write(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_canonical_contract_is_complete_and_drives_the_frozen_recovery_matrix() -> None:
    contract = OnlyProductApiContractV2(CONTRACT)
    by_tool: dict[OnlyAgentToolClass, set[OnlyAgentToolRecoveryClass]] = {}
    document = _document()
    for _, _, operation in _operations(document):
        metadata = operation.get(EXTENSION)
        if not isinstance(metadata, dict):
            continue
        tool = OnlyAgentToolClass(metadata["tool_class"])
        loaded = contract.load_operation_verified(2, contract.fingerprint, operation["operationId"])
        by_tool.setdefault(tool, set()).add(loaded.recovery_class)
        assert loaded.http_path.startswith("/api/v2/")
        assert loaded.http_method in {"GET", "POST"}
    assert by_tool == {
        OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY: {OnlyAgentToolRecoveryClass.IMMUTABLE_EXACT_QUERY},
        OnlyAgentToolClass.RESEARCH_DEFINITION_RESOLVE: {OnlyAgentToolRecoveryClass.PURE_RESOLVE},
        OnlyAgentToolClass.RESEARCH_RUN_SUBMIT: {OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND},
        OnlyAgentToolClass.RESEARCH_RUN_QUERY: {OnlyAgentToolRecoveryClass.MUTABLE_OBSERVATION_QUERY},
        OnlyAgentToolClass.RESEARCH_EVIDENCE_QUERY: {OnlyAgentToolRecoveryClass.IMMUTABLE_EXACT_QUERY},
        OnlyAgentToolClass.SYMBOLIC_SEARCH: {OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND},
        OnlyAgentToolClass.PARAMETER_SEARCH: {OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND},
        OnlyAgentToolClass.SEARCH_QUERY: {OnlyAgentToolRecoveryClass.MUTABLE_OBSERVATION_QUERY},
    }
    exact = contract.load_operation_verified(
        2, contract.fingerprint, _operation_id(document, "EXACT_CATALOG_CONTEXT_QUERY")
    )
    assert {
        "ordered_calculation_capabilities",
        "ordered_registered_universes",
        "ordered_dataset_field_contracts",
        "ordered_statistics_capabilities",
    }.issubset(set(cast(list[str], exact.response_schema["required"])))


def _operation_id(document: dict[str, object], tool_class: str, contains: str = "") -> str:
    matches = [
        operation["operationId"]
        for _, _, operation in _operations(document)
        if operation.get(EXTENSION, {}).get("tool_class") == tool_class
        and contains in cast(str, operation.get("operationId"))
    ]
    assert len(matches) == 1
    return cast(str, matches[0])


def _plan(
    contract: OnlyProductApiContractV2,
    operation_id: str,
    tool_class: OnlyAgentToolClass,
    request: dict[str, object],
    *,
    command_id: str | None = None,
) -> OnlyAgentToolCallPlanV1:
    return OnlyAgentToolCallPlanV1(
        "1" * 64,
        0,
        "2" * 64,
        tool_class,
        2,
        contract.fingerprint,
        operation_id,
        request,
        exact_identity_inputs=(OnlyAgentContextReferenceV1("SEARCH_EXPERIMENT", 1, "a" * 64),)
        if "experiment_fingerprint" in request
        else (),
        product_command_id_or_idempotency_key=command_id,
        tool_policy_fingerprint="3" * 64,
    )


def test_wire_projection_comes_only_from_plan_and_canonical_contract() -> None:
    contract = OnlyProductApiContractV2(CONTRACT)
    config = OnlyProductApiEndpointConfigV1(
        "https://product.invalid",
        "product-secret",
        CONTRACT,
    )
    document = _document()
    catalog_id = _operation_id(document, "EXACT_CATALOG_CONTEXT_QUERY")
    catalog = _plan(
        contract,
        catalog_id,
        OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        {"catalog_generation_fingerprint": "a" * 64},
    )
    request = contract.wire_request_verified(catalog, config)
    assert request.method == "GET"
    assert request.url == f"https://product.invalid/api/v2/research/catalog-context/exact/{'a' * 64}"
    assert request.body == b""
    assert "product-secret" not in repr(request)

    run_id = "00000000-0000-4000-8000-000000000123"
    run_operation = _operation_id(document, "RESEARCH_RUN_QUERY")
    run = _plan(
        contract,
        run_operation,
        OnlyAgentToolClass.RESEARCH_RUN_QUERY,
        {"run_id": run_id},
    )
    run_request = contract.wire_request_verified(run, config)
    assert run_request.url.endswith(f"/api/v2/research/runs/{run_id}")

    command_id = "00000000-0000-4000-8000-000000000124"
    advance_operation = _operation_id(document, "SYMBOLIC_SEARCH", "advance")
    advance = _plan(
        contract,
        advance_operation,
        OnlyAgentToolClass.SYMBOLIC_SEARCH,
        {
            "schema_version": 1,
            "method": "SYMBOLIC",
            "operation": "ADVANCE_ONE_SYMBOLIC_OCCURRENCE",
            "experiment_fingerprint": "a" * 64,
            "expected_state": {},
        },
        command_id=command_id,
    )
    first = contract.wire_request_verified(advance, config)
    second = contract.wire_request_verified(advance, config)
    assert first == second
    assert first.headers["Idempotency-Key"] == command_id
    assert first.url.endswith("/api/v2/research/search/symbolic-experiments/advance")
    assert json.loads(first.body)["experiment_fingerprint"] == "a" * 64

    injected = _plan(
        contract,
        catalog_id,
        OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        {"catalog_generation_fingerprint": "a" * 64, "url": "https://attacker.invalid"},
    )
    with pytest.raises(ValueError, match="AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED"):
        contract.wire_request_verified(injected, config)


def _unknown_field(document):  # type: ignore[no-untyped-def]
    _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")[EXTENSION]["unknown"] = True


def _unknown_tool(document):  # type: ignore[no-untyped-def]
    _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")[EXTENSION]["tool_class"] = "SHELL"


def _unknown_recovery(document):  # type: ignore[no-untyped-def]
    _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")[EXTENSION]["recovery_class"] = "RETRY"


def _duplicate_operation_id(document):  # type: ignore[no-untyped-def]
    operations = [operation for _, _, operation in _operations(document)]
    operations[1]["operationId"] = operations[0]["operationId"]


def _missing_tool_operation(document):  # type: ignore[no-untyped-def]
    del _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")[EXTENSION]


def _identity_missing_field(document):  # type: ignore[no-untyped-def]
    _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")[EXTENSION]["identity_requirements"] = ["latest"]


def _identity_missing_kind(document):  # type: ignore[no-untyped-def]
    operation = _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")
    parameter = operation["parameters"][0]
    del parameter["schema"]["x-onlyalpha-reference-kind"]


def _identity_missing_version(document):  # type: ignore[no-untyped-def]
    operation = _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")
    del operation["parameters"][0]["schema"]["x-onlyalpha-reference-schema-version"]


def _identity_invalid_locator(document):  # type: ignore[no-untyped-def]
    operation = _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")
    operation["parameters"][0]["schema"]["x-onlyalpha-reference-locator-kind"] = "PATH"


def _research_run_as_sha(document):  # type: ignore[no-untyped-def]
    operation = _agent_operation(document, "RESEARCH_RUN_QUERY")
    operation["parameters"][0]["schema"]["x-onlyalpha-reference-locator-kind"] = "SHA256"


def _sha_owner_as_uuid(document):  # type: ignore[no-untyped-def]
    operation = _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")
    operation["parameters"][0]["schema"]["x-onlyalpha-reference-locator-kind"] = "UUID4"


def _idempotent_without_command(document):  # type: ignore[no-untyped-def]
    operation = _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")
    operation[EXTENSION]["recovery_class"] = "IDEMPOTENT_COMMAND"


def _mutable_replay_safe(document):  # type: ignore[no-untyped-def]
    _agent_operation(document, "RESEARCH_RUN_QUERY")["x-onlyalpha-replay-safe"] = True


def _wrong_owner_kind(document):  # type: ignore[no-untyped-def]
    operation = _agent_operation(document, "EXACT_CATALOG_CONTEXT_QUERY")
    operation[EXTENSION]["owning_authority_references"][0]["reference_kind"] = "SEARCH_EXPERIMENT"


def _missing_command_response_identity(document):  # type: ignore[no-untyped-def]
    operation = _agent_operation(document, "RESEARCH_RUN_SUBMIT")
    del operation["responses"]["202"]["headers"]["Idempotency-Key"]


def _missing_command_effect_semantics(document):  # type: ignore[no-untyped-def]
    del _agent_operation(document, "RESEARCH_RUN_SUBMIT")[EXTENSION]["response_effect_semantics"]


@pytest.mark.parametrize(
    "mutate",
    [
        _unknown_field,
        _unknown_tool,
        _unknown_recovery,
        _duplicate_operation_id,
        _missing_tool_operation,
        _identity_missing_field,
        _identity_missing_kind,
        _identity_missing_version,
        _identity_invalid_locator,
        _research_run_as_sha,
        _sha_owner_as_uuid,
        _idempotent_without_command,
        _mutable_replay_safe,
        _wrong_owner_kind,
        _missing_command_response_identity,
        _missing_command_effect_semantics,
    ],
)
def test_contract_semantic_corruption_fails_closed(
    tmp_path: Path,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    document = copy.deepcopy(_document())
    mutate(document)
    with pytest.raises(ValueError, match="AGENT_PRODUCT_API_CONTRACT_MISMATCH"):
        OnlyProductApiContractV2(_write(tmp_path, document))


class _IdempotentProductServer:
    def __init__(self, command_id: str, *, first_mode: str = "close", response_body: bytes = b"{}") -> None:
        self.command_id = command_id
        self.request_count = 0
        self.observed_command_ids: list[str | None] = []
        self.observed_requests: list[tuple[str, str, bytes]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                outer.request_count += 1
                outer.observed_command_ids.append(self.headers.get("Idempotency-Key"))
                outer.observed_requests.append((self.command, self.path, body))
                if outer.request_count == 1 and first_mode == "close":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                response = response_body
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.send_header("Idempotency-Key", outer.command_id)
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, _format: str, *args: object) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _io_permit(session_fingerprint: str):  # type: ignore[no-untyped-def]
    runtime_permit = _mint_runtime_execution_permit(  # noqa: SLF001 - certification of sealed gate
        session_fingerprint,
        "4" * 64,
        "5" * 64,
        "6" * 40,
    )
    return _mint_external_io_permit(  # noqa: SLF001 - certification of sealed gate
        runtime_permit,
        agent_session_fingerprint=session_fingerprint,
    )


def test_lost_product_command_response_reconciles_with_same_exact_command_identity() -> None:
    command_id = "00000000-0000-4000-8000-000000000124"
    server = _IdempotentProductServer(command_id)
    try:
        contract = OnlyProductApiContractV2(CONTRACT)
        operation_id = _operation_id(_document(), "SYMBOLIC_SEARCH", "advance")
        plan = _plan(
            contract,
            operation_id,
            OnlyAgentToolClass.SYMBOLIC_SEARCH,
            {
                "schema_version": 1,
                "method": "SYMBOLIC",
                "operation": "ADVANCE_ONE_SYMBOLIC_OCCURRENCE",
                "experiment_fingerprint": "a" * 64,
                "expected_state": {},
            },
            command_id=command_id,
        )
        config = OnlyProductApiEndpointConfigV1(server.base_url, "product-secret", CONTRACT)
        adapter = OnlyContractDrivenProductApiAdapterV1(
            config,
            OnlyRawHttpTransportV1(
                connect_timeout_seconds=0.2,
                read_timeout_seconds=0.2,
                verify_tls=True,
                ca_bundle_path=None,
            ),
        )
        first = adapter.invoke(plan, _io_permit(plan.agent_session_fingerprint))
        assert first.classification is OnlyHttpDispatchClassification.POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE
        second = adapter.invoke(plan, _io_permit(plan.agent_session_fingerprint))
        assert second.classification is OnlyHttpDispatchClassification.RESPONSE_RECEIVED
        assert server.request_count == 2
        assert server.observed_command_ids == [command_id, command_id]
        assert server.observed_requests[0] == server.observed_requests[1]
    finally:
        server.close()


def test_raw_transport_rejects_fake_or_consumed_io_capability_before_network() -> None:
    command_id = "00000000-0000-4000-8000-000000000124"
    server = _IdempotentProductServer(command_id)
    try:
        contract = OnlyProductApiContractV2(CONTRACT)
        operation_id = _operation_id(_document(), "SYMBOLIC_SEARCH", "advance")
        plan = _plan(
            contract,
            operation_id,
            OnlyAgentToolClass.SYMBOLIC_SEARCH,
            {
                "schema_version": 1,
                "method": "SYMBOLIC",
                "operation": "ADVANCE_ONE_SYMBOLIC_OCCURRENCE",
                "experiment_fingerprint": "a" * 64,
                "expected_state": {},
            },
            command_id=command_id,
        )
        config = OnlyProductApiEndpointConfigV1(server.base_url, "product-secret", CONTRACT)
        transport = OnlyRawHttpTransportV1(
            connect_timeout_seconds=0.2,
            read_timeout_seconds=0.2,
            verify_tls=True,
            ca_bundle_path=None,
        )
        request = contract.wire_request_verified(plan, config)
        with pytest.raises(OnlyAgentContextError, match="AGENT_POLICY_VIOLATION"):
            transport.send(request, cast(Any, object()))
        permit = _io_permit(plan.agent_session_fingerprint)
        first = transport.send(request, permit)
        assert first.classification is OnlyHttpDispatchClassification.POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE
        with pytest.raises(OnlyAgentContextError, match="AGENT_POLICY_VIOLATION"):
            transport.send(request, permit)
        assert server.request_count == 1
    finally:
        server.close()


def test_oversized_post_dispatch_response_is_effect_ambiguous() -> None:
    command_id = "00000000-0000-4000-8000-000000000124"
    server = _IdempotentProductServer(command_id, first_mode="response", response_body=b"x" * 32)
    try:
        contract = OnlyProductApiContractV2(CONTRACT)
        operation_id = _operation_id(_document(), "SYMBOLIC_SEARCH", "advance")
        plan = _plan(
            contract,
            operation_id,
            OnlyAgentToolClass.SYMBOLIC_SEARCH,
            {
                "schema_version": 1,
                "method": "SYMBOLIC",
                "operation": "ADVANCE_ONE_SYMBOLIC_OCCURRENCE",
                "experiment_fingerprint": "a" * 64,
                "expected_state": {},
            },
            command_id=command_id,
        )
        adapter = OnlyContractDrivenProductApiAdapterV1(
            OnlyProductApiEndpointConfigV1(server.base_url, "product-secret", CONTRACT),
            OnlyRawHttpTransportV1(
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                verify_tls=True,
                ca_bundle_path=None,
                maximum_response_bytes=8,
            ),
        )
        outcome = adapter.invoke(plan, _io_permit(plan.agent_session_fingerprint))
        assert outcome.classification is OnlyHttpDispatchClassification.POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE
    finally:
        server.close()
