"""API-backed transient readers for owning Product authorities."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from urllib.parse import quote

from onlyalpha.application.search_product import (
    OnlyParameterExpectedStateV1,
    OnlySearchBoundedOperationV1,
    OnlySearchMethodV1,
    OnlySearchPlanExpectedStateV1,
    OnlySearchTerminalKindV1,
    OnlySearchTerminalProjectionV1,
    OnlySymbolicExpectedStateV1,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.agent.authority_state import (
    OnlyAgentResearchStateReader,
    OnlyAgentSearchAuthorityViewV1,
    OnlyAgentSearchStateReader,
)
from onlyalpha.research.agent.errors import OnlyAgentContextError
from onlyalpha.research.agent.model import OnlyAgentEvaluationContextReferenceV1
from onlyalpha.research.agent.occurrence import (
    OnlyAgentExactAuthorityReference,
    OnlyAgentExactAuthorityReferenceV2,
    OnlyAgentReferenceLocatorKind,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunId,
    OnlyResearchRunState,
)
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .config import OnlyProductApiEndpointConfigV1


class OnlyAgentProductControlPlaneClient(Protocol):
    def get_json_verified(self, path: str) -> Mapping[str, object]: ...


class OnlyAgentProductHttpControlPlaneClientV1:
    """One exact-origin GET client with no retry, redirect, cookie, or proxy."""

    def __init__(self, config: OnlyProductApiEndpointConfigV1) -> None:
        self._config = config

    def get_json_verified(self, path: str) -> Mapping[str, object]:
        if not path.startswith("/api/v2/") or "?" in path or "#" in path:
            raise OnlyAgentContextError("AGENT_POLICY_VIOLATION", "Product control-plane path")
        request = urllib.request.Request(
            self._config.base_url + path,
            headers={"Accept": "application/json", "Authorization": f"Bearer {self._config.bearer_token}"},
            method="GET",
        )
        context = None
        if self._config.base_url.startswith("https://"):
            import ssl

            context = ssl.create_default_context(
                cafile=str(self._config.ca_bundle_path) if self._config.ca_bundle_path else None
            )
            if not self._config.verify_tls:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
        handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({}), _NoRedirectHandler()]
        if context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=context))
        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(request, timeout=self._config.read_timeout_seconds) as response:
                raw = response.read()
                if response.status != 200 or response.headers.get_content_type() != "application/json":
                    raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "Product control-plane response")
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise OnlyAgentContextError("AGENT_TOOL_CALL_FAILED", "Product API unavailable") from exc
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "Product control-plane JSON") from exc
        return _mapping(value, "response")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


@dataclass(frozen=True, slots=True)
class _SerializedFact:
    payload: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


class OnlyApiBackedAgentSearchStateReaderV1(OnlyAgentSearchStateReader):
    """Build one coherent transient Search view through Ledger/Terminal/Ledger."""

    def __init__(self, client: OnlyAgentProductControlPlaneClient) -> None:
        self._client = client

    def load_search_state_verified(self, experiment_fingerprint: str) -> OnlyAgentSearchAuthorityViewV1:
        _sha(experiment_fingerprint, "experiment_fingerprint")
        base = f"/api/v2/research/search/experiments/{quote(experiment_fingerprint, safe='')}"
        first = self._client.get_json_verified(base + "/ledger")
        terminal_payload = self._client.get_json_verified(base + "/terminal")
        second = self._client.get_json_verified(base + "/ledger")
        if _canonical(first) != _canonical(second):
            raise OnlyAgentContextError("AGENT_AUTHORITY_OBSERVATION_UNSTABLE", experiment_fingerprint)
        ledger = _strict_envelope(first, {"schema_version", "experiment_fingerprint", "method", "ledger"})
        terminal_wire = _strict_envelope(
            terminal_payload,
            {"schema_version", "experiment_fingerprint", "method", "terminal_kind", "terminal_fact", "stop_reason"},
        )
        if ledger["schema_version"] != 1 or terminal_wire["schema_version"] != 1:
            raise OnlyAgentContextError("AGENT_SEARCH_FAILED", "unsupported Search projection schema")
        method = OnlySearchMethodV1(_string(ledger["method"], "method"))
        if (
            ledger["experiment_fingerprint"] != experiment_fingerprint
            or terminal_wire["experiment_fingerprint"] != experiment_fingerprint
            or terminal_wire["method"] != method.value
        ):
            raise OnlyAgentContextError("AGENT_SEARCH_FAILED", "Search projection identity mismatch")
        body = _mapping(ledger["ledger"], "ledger")
        if body.get("method") != method.value or body.get("experiment_fingerprint") != experiment_fingerprint:
            raise OnlyAgentContextError("AGENT_SEARCH_FAILED", "Search ledger identity mismatch")
        expected = _expected_state(method, _mapping(body.get("expected_state"), "expected_state"))
        terminal_kind = OnlySearchTerminalKindV1(_string(terminal_wire["terminal_kind"], "terminal_kind"))
        fact_payload = terminal_wire["terminal_fact"]
        fact = None if fact_payload is None else _SerializedFact(_mapping(fact_payload, "terminal_fact"))
        stop_reason = terminal_wire["stop_reason"]
        if stop_reason is not None and not isinstance(stop_reason, str):
            raise OnlyAgentContextError("AGENT_SEARCH_FAILED", "Search stop reason")
        terminal = OnlySearchTerminalProjectionV1(method, experiment_fingerprint, terminal_kind, fact, stop_reason)
        operation = _next_operation(method, terminal_kind, body)
        return OnlyAgentSearchAuthorityViewV1(terminal, expected, operation)


class OnlyApiBackedAgentResearchStateReaderV1(OnlyAgentResearchStateReader):
    """Strict UUID-addressed Research Run observation through Product API."""

    def __init__(self, client: OnlyAgentProductControlPlaneClient) -> None:
        self._client = client

    def load_research_run_verified(self, run_reference: OnlyAgentExactAuthorityReference) -> OnlyResearchRun:
        if (
            not isinstance(run_reference, OnlyAgentExactAuthorityReferenceV2)
            or run_reference.reference_kind != "RESEARCH_RUN"
            or run_reference.reference_schema_version != 1
            or run_reference.locator_kind is not OnlyAgentReferenceLocatorKind.UUID4
        ):
            raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", "RESEARCH_RUN")
        run_id = OnlyResearchRunId(run_reference.locator_value)
        payload = self._client.get_json_verified(f"/api/v2/research/runs/{quote(run_id.value, safe='')}")
        try:
            run = _research_run(payload)
        except Exception as exc:
            if isinstance(exc, OnlyAgentContextError):
                raise
            raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", "RESEARCH_RUN") from exc
        if run.run_id != run_id:
            raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", "RESEARCH_RUN")
        return run


@dataclass(frozen=True, slots=True)
class OnlyApiCatalogGenerationIdentityV1:
    generation_fingerprint: str


@dataclass(frozen=True, slots=True)
class OnlyApiDatasetSnapshotIdentityV1:
    snapshot_fingerprint: str

    @property
    def snapshot(self) -> OnlyApiDatasetSnapshotIdentityV1:
        return self


@dataclass(frozen=True, slots=True)
class OnlyApiEvaluationContextIdentityV1:
    evaluation_kind: str
    evaluation_schema_version: int
    evaluation_fingerprint: str


class OnlyApiBackedAgentBriefReferenceReaderV1:
    """Exact identity-only Brief verification through Product API v2."""

    def __init__(self, client: OnlyAgentProductControlPlaneClient) -> None:
        self._client = client

    def generation(self, fingerprint: str) -> OnlyApiCatalogGenerationIdentityV1:
        _sha(fingerprint, "catalog_generation_fingerprint")
        payload = self._client.get_json_verified(f"/api/v2/research/catalog-context/exact/{fingerprint}")
        if payload.get("catalog_generation_fingerprint") != fingerprint:
            raise OnlyAgentContextError("AGENT_RESEARCH_BRIEF_REFERENCE_INVALID", fingerprint)
        return OnlyApiCatalogGenerationIdentityV1(fingerprint)

    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyApiDatasetSnapshotIdentityV1:
        _sha(snapshot_fingerprint, "dataset_snapshot_fingerprint")
        payload = _strict_envelope(
            self._client.get_json_verified(f"/api/v2/research/datasets/{snapshot_fingerprint}"),
            {"schema_version", "snapshot_fingerprint"},
        )
        if payload["schema_version"] != 1 or payload["snapshot_fingerprint"] != snapshot_fingerprint:
            raise OnlyAgentContextError("AGENT_RESEARCH_BRIEF_REFERENCE_INVALID", snapshot_fingerprint)
        return OnlyApiDatasetSnapshotIdentityV1(snapshot_fingerprint)

    def load_evaluation_context_verified(
        self, reference: OnlyAgentEvaluationContextReferenceV1
    ) -> OnlyApiEvaluationContextIdentityV1:
        path = (
            "/api/v2/research/evaluations/"
            f"{quote(reference.evaluation_kind, safe='')}/{reference.evaluation_schema_version}/"
            f"{reference.evaluation_fingerprint}"
        )
        payload = _strict_envelope(
            self._client.get_json_verified(path),
            {"schema_version", "evaluation_kind", "evaluation_schema_version", "evaluation_fingerprint"},
        )
        expected = (reference.evaluation_kind, reference.evaluation_schema_version, reference.evaluation_fingerprint)
        actual = (
            payload["evaluation_kind"],
            payload["evaluation_schema_version"],
            payload["evaluation_fingerprint"],
        )
        if payload["schema_version"] != 1 or actual != expected:
            raise OnlyAgentContextError("AGENT_RESEARCH_BRIEF_REFERENCE_INVALID", reference.evaluation_fingerprint)
        return OnlyApiEvaluationContextIdentityV1(*expected)


def _research_run(value: Mapping[str, object]) -> OnlyResearchRun:
    required = {
        "schema_version",
        "run_id",
        "revision",
        "state",
        "specification_schema_version",
        "specification_fingerprint",
        "admission_resolution_fingerprint",
        "specification",
        "queued_at",
        "started_at",
        "cancel_requested_at",
        "finished_at",
        "result_ref",
        "artifact_ref",
        "failure",
    }
    payload = _strict_envelope(value, required)
    if payload["schema_version"] != 2:
        raise ValueError("Research Run schema")
    specification = OnlyResearchSpecification.from_dict(_mapping(payload["specification"], "specification"))
    if payload["specification_schema_version"] != specification.schema_version:
        raise ValueError("Research specification schema")
    failure_payload = payload["failure"]
    failure = None
    if failure_payload is not None:
        item = _strict_envelope(_mapping(failure_payload, "failure"), {"phase", "code", "detail"})
        failure = OnlyResearchRunFailure(
            OnlyResearchRunFailurePhase(_string(item["phase"], "failure.phase")),
            _string(item["code"], "failure.code"),
            _string(item["detail"], "failure.detail"),
        )
    return OnlyResearchRun(
        OnlyResearchRunId(_string(payload["run_id"], "run_id")),
        int(_string(payload["revision"], "revision")),
        OnlyResearchRunState(_string(payload["state"], "state")),
        specification,
        _string(payload["specification_fingerprint"], "specification_fingerprint"),
        only_canonical_json(specification.to_dict()),
        _string(payload["admission_resolution_fingerprint"], "admission_resolution_fingerprint"),
        _required_time(payload["queued_at"]),
        _time(payload["started_at"]),
        _time(payload["cancel_requested_at"]),
        _time(payload["finished_at"]),
        _optional_string(payload["result_ref"]),
        _optional_string(payload["artifact_ref"]),
        failure,
        (),
        None,
    )


def _expected_state(
    method: OnlySearchMethodV1, value: Mapping[str, object]
) -> OnlySymbolicExpectedStateV1 | OnlyParameterExpectedStateV1:
    if method is OnlySearchMethodV1.SYMBOLIC:
        return OnlySymbolicExpectedStateV1(
            _string(value.get("experiment_fingerprint"), "experiment_fingerprint"),
            _optional_string(value.get("enumeration_result_fingerprint")),
            tuple(_plan_state(item) for item in _sequence(value.get("ordered_plan_states"), "ordered_plan_states")),
            _integer(value.get("next_iteration_ordinal"), "next_iteration_ordinal"),
            _integer(value.get("research_attempt_count"), "research_attempt_count"),
            _integer(value.get("qualification_attempt_count"), "qualification_attempt_count"),
            _optional_string(value.get("target_plan_fingerprint")),
            _integer(value.get("schema_version"), "schema_version"),
        )
    return OnlyParameterExpectedStateV1(
        _string(value.get("experiment_fingerprint"), "experiment_fingerprint"),
        _optional_string(value.get("frontier_fingerprint")),
        tuple(
            _string(item, "feedback_decision")
            for item in _sequence(value.get("ordered_feedback_decision_fingerprints"), "decisions")
        ),
        tuple(_plan_state(item) for item in _sequence(value.get("frontier_plan_states"), "frontier_plan_states")),
        _integer(value.get("proposal_count"), "proposal_count"),
        _integer(value.get("research_attempt_count"), "research_attempt_count"),
        _integer(value.get("qualification_attempt_count"), "qualification_attempt_count"),
        _integer(value.get("schema_version"), "schema_version"),
    )


def _plan_state(value: object) -> OnlySearchPlanExpectedStateV1:
    payload = _strict_envelope(
        _mapping(value, "plan_state"),
        {"plan_fingerprint", "result_fingerprint", "research_product_command_id", "research_receipt_outcome_id"},
    )
    return OnlySearchPlanExpectedStateV1(
        _string(payload["plan_fingerprint"], "plan_fingerprint"),
        _optional_string(payload["result_fingerprint"]),
        _optional_string(payload["research_product_command_id"]),
        _optional_string(payload["research_receipt_outcome_id"]),
    )


def _next_operation(
    method: OnlySearchMethodV1, terminal: OnlySearchTerminalKindV1, ledger: Mapping[str, object]
) -> OnlySearchBoundedOperationV1 | None:
    if terminal is not OnlySearchTerminalKindV1.NON_TERMINAL:
        return None
    plans = _sequence(ledger.get("plans"), "plans")
    results = _sequence(ledger.get("results"), "results")
    if len(plans) != len(results):
        raise OnlyAgentContextError("AGENT_SEARCH_FAILED", "Search ledger shape")
    open_plan = any(result is None for result in results)
    if method is OnlySearchMethodV1.SYMBOLIC:
        return (
            OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE
            if open_plan
            else OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE
        )
    return (
        OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH
        if open_plan
        else OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION
    )


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", field)
    return cast(Mapping[str, object], value)


def _strict_envelope(value: Mapping[str, object], fields: set[str]) -> Mapping[str, object]:
    if set(value) != fields:
        raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "unexpected Product response fields")
    return value


def _sequence(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", field)
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", field)
    return value


def _optional_string(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "optional string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", field)
    return value


def _sha(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise OnlyAgentContextError("AGENT_EXACT_AUTHORITY_REFERENCE_INVALID", field)


def _time(value: object) -> datetime | None:
    if value is None:
        return None
    text = _string(value, "timestamp")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp timezone")
    return parsed.astimezone(UTC)


def _required_time(value: object) -> datetime:
    parsed = _time(value)
    if parsed is None:
        raise OnlyAgentContextError("AGENT_TOOL_RESULT_INVALID", "timestamp")
    return parsed


__all__ = [name for name in globals() if name.startswith("Only")]
