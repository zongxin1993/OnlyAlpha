from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import onlyalpha_agent_orchestrator.driver as driver_module
import pytest
from onlyalpha_agent_orchestrator.bindings import (
    OnlyAgentModelInvocationBindingV1,
    OnlyStaticAgentModelInvocationBindingReaderV1,
)
from onlyalpha_agent_orchestrator.coordination import (
    OnlyAgentSessionExecutionBusy,
    OnlyAgentSessionExecutionCoordinatorV1,
)
from onlyalpha_agent_orchestrator.driver import OnlyAgentSessionDriverV1

from onlyalpha.research.agent import (
    OnlyAgentDecisionKind,
    OnlyAgentDerivedSessionStateV1,
    OnlyAgentDerivedSessionStatus,
    OnlyAgentModelSettingBindingV1,
    OnlyAgentModelSettingState,
    OnlyAgentNextActionKind,
    OnlyAgentNextActionV1,
    OnlyAgentSessionReducerV1,
    OnlyAgentToolClass,
)

SESSION = "a" * 64


def _binding(*, model_id: str = "model-a") -> OnlyAgentModelInvocationBindingV1:
    return OnlyAgentModelInvocationBindingV1(
        "RESEARCH_PLANNER",
        "provider-a",
        model_id,
        "2026-09-01",
        "1" * 64,
        "2" * 64,
        "3" * 64,
        (OnlyAgentModelSettingBindingV1("temperature", OnlyAgentModelSettingState.VALUE, 0),),
    )


def test_invocation_binding_is_explicit_role_keyed_and_contains_no_operational_secret_fields() -> None:
    first = _binding()
    changed = _binding(model_id="model-b")
    reader = OnlyStaticAgentModelInvocationBindingReaderV1((first,))
    assert reader.load_model_invocation_binding_verified("RESEARCH_PLANNER") == first
    assert first != changed
    assert set(first.to_dict()) == {
        "schema_version",
        "logical_role",
        "provider_id",
        "model_id",
        "model_version",
        "prompt_template_fingerprint",
        "structured_output_schema_fingerprint",
        "model_execution_policy_fingerprint",
        "response_affecting_settings",
    }
    assert not {"api_key", "token", "credential", "base_url", "proxy", "timeout", "tls"}.intersection(first.to_dict())
    with pytest.raises(ValueError, match="BINDING_MISSING"):
        reader.load_model_invocation_binding_verified("SEARCH_ROUTER")


def test_invocation_binding_rejects_secret_or_operational_setting_names() -> None:
    with pytest.raises(ValueError, match="SECRET_FORBIDDEN"):
        OnlyAgentModelInvocationBindingV1(
            "RESEARCH_PLANNER",
            "provider-a",
            "model-a",
            "v1",
            "1" * 64,
            "2" * 64,
            "3" * 64,
            (OnlyAgentModelSettingBindingV1("api_key", OnlyAgentModelSettingState.VALUE, "secret"),),
        )


def test_invocation_binding_allows_legitimate_response_affecting_output_limit() -> None:
    binding = OnlyAgentModelInvocationBindingV1(
        "RESEARCH_PLANNER",
        "provider-a",
        "model-a",
        "v1",
        "1" * 64,
        "2" * 64,
        "3" * 64,
        (OnlyAgentModelSettingBindingV1("max_output_tokens", OnlyAgentModelSettingState.VALUE, 4096),),
    )
    assert binding.response_affecting_settings[0].setting_name == "max_output_tokens"


def test_same_session_coordination_allows_exactly_one_critical_section(tmp_path: Path) -> None:
    coordinator = OnlyAgentSessionExecutionCoordinatorV1(tmp_path / "locks")
    entered = threading.Event()
    release = threading.Event()
    outcome: list[str] = []

    def holder() -> None:
        with coordinator.acquire(SESSION):
            outcome.append("holder")
            entered.set()
            assert release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert entered.wait(5)
    with pytest.raises(OnlyAgentSessionExecutionBusy):
        with coordinator.acquire(SESSION):
            outcome.append("contender")
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    with coordinator.acquire(SESSION):
        outcome.append("fresh")
    assert outcome == ["holder", "fresh"]


def test_concurrent_drivers_allow_one_action_and_contender_has_zero_mutation_or_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()
    mutations: list[str] = []
    io_calls: list[str] = []
    action = OnlyAgentNextActionV1(
        OnlyAgentNextActionKind.DERIVE_DECISION,
        decision_kind=OnlyAgentDecisionKind.RESEARCH_PLAN,
    )

    class BlockingReducer:
        def __init__(self) -> None:
            self.calls = 0

        def derive(self, _session: str) -> OnlyAgentDerivedSessionStateV1:
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert release.wait(5)
            status = OnlyAgentDerivedSessionStatus.ACTIVE if self.calls == 1 else OnlyAgentDerivedSessionStatus.COMPLETE
            return OnlyAgentDerivedSessionStateV1(SESSION, status, action if status.value == "ACTIVE" else None)

    reducer = BlockingReducer()
    materializer = _Materializer()
    original_derive = materializer.derive_decision

    def record_decision(**kwargs):  # type: ignore[no-untyped-def]
        mutations.append("decision")
        original_derive(**kwargs)

    materializer.derive_decision = record_decision  # type: ignore[method-assign]
    manifest = SimpleNamespace(implementation_fingerprint="4" * 64, source_revision="5" * 40)
    permit = SimpleNamespace(historical_workflow_resource_fingerprint="6" * 64)
    monkeypatch.setattr(driver_module, "build_current_agent_workflow_implementation_manifest", lambda: manifest)
    monkeypatch.setattr(driver_module, "assert_runtime_execution_permit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        driver_module,
        "execute_after_runtime_admission",
        lambda _session, _reader, continuation: continuation(permit),
    )
    monkeypatch.setattr(driver_module, "execute_external_model_occurrence", lambda **_kwargs: io_calls.append("model"))
    monkeypatch.setattr(driver_module, "execute_external_tool_occurrence", lambda **_kwargs: io_calls.append("tool"))
    coordinator = OnlyAgentSessionExecutionCoordinatorV1(tmp_path / "locks")

    def new_driver() -> OnlyAgentSessionDriverV1:
        return OnlyAgentSessionDriverV1(
            reducer=reducer,  # type: ignore[arg-type]
            sessions=object(),  # type: ignore[arg-type]
            materializer=materializer,  # type: ignore[arg-type]
            model_occurrences=object(),  # type: ignore[arg-type]
            tool_occurrences=object(),  # type: ignore[arg-type]
            model_adapter=object(),  # type: ignore[arg-type]
            product_adapter=object(),  # type: ignore[arg-type]
            coordination=coordinator,
        )

    first_error: list[BaseException] = []

    def first() -> None:
        try:
            new_driver().advance_once(SESSION)
        except BaseException as exc:  # pragma: no cover - assertion transport from thread
            first_error.append(exc)

    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(5)
    with pytest.raises(OnlyAgentSessionExecutionBusy):
        new_driver().advance_once(SESSION)
    assert mutations == []
    assert io_calls == []
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert first_error == []
    assert mutations == ["decision"]
    assert io_calls == []


class _Coordinator:
    @contextmanager
    def acquire(self, _session: str):  # type: ignore[no-untyped-def]
        yield


class _Reducer:
    def __init__(self, action: OnlyAgentNextActionV1) -> None:
        self.action = action
        self.calls = 0

    def derive(self, _session: str) -> OnlyAgentDerivedSessionStateV1:
        self.calls += 1
        if self.calls == 1:
            return OnlyAgentDerivedSessionStateV1(SESSION, OnlyAgentDerivedSessionStatus.ACTIVE, self.action)
        return OnlyAgentDerivedSessionStateV1(SESSION, OnlyAgentDerivedSessionStatus.COMPLETE, None)


class _Materializer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def prepare_model_call(self, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("prepare_model")
        return object()

    def prepare_tool_call(self, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("prepare_tool")
        return object()

    def derive_decision(self, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("derive_decision")

    def reconstruct_launch(self, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls.append("reconstruct_launch")


class _Models:
    def __init__(self) -> None:
        self.recoveries = 0

    def recover_outcome_unknown(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        self.recoveries += 1


class _Tools:
    def __init__(self) -> None:
        self.recoveries = 0

    def prepare_recovery(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        self.recoveries += 1
        return object()


@pytest.mark.parametrize(
    ("action", "expected_materializer", "model_io", "tool_io", "model_recovery", "tool_recovery"),
    (
        (
            OnlyAgentNextActionV1(OnlyAgentNextActionKind.PREPARE_MODEL_CALL, logical_role="RESEARCH_PLANNER"),
            "prepare_model",
            1,
            0,
            0,
            0,
        ),
        (
            OnlyAgentNextActionV1(
                OnlyAgentNextActionKind.DERIVE_DECISION,
                decision_kind=OnlyAgentDecisionKind.RESEARCH_PLAN,
            ),
            "derive_decision",
            0,
            0,
            0,
            0,
        ),
        (
            OnlyAgentNextActionV1(
                OnlyAgentNextActionKind.PREPARE_TOOL_CALL,
                tool_class=OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
            ),
            "prepare_tool",
            0,
            1,
            0,
            0,
        ),
        (
            OnlyAgentNextActionV1(
                OnlyAgentNextActionKind.RECOVER_MODEL_OUTCOME_UNKNOWN,
                occurrence_fingerprint="1" * 64,
            ),
            None,
            0,
            0,
            1,
            0,
        ),
        (
            OnlyAgentNextActionV1(
                OnlyAgentNextActionKind.RECOVER_TOOL_OCCURRENCE,
                occurrence_fingerprint="2" * 64,
            ),
            None,
            0,
            1,
            0,
            1,
        ),
        (
            OnlyAgentNextActionV1(
                OnlyAgentNextActionKind.RECONSTRUCT_LAUNCH_RECORD,
                occurrence_fingerprint="3" * 64,
            ),
            "reconstruct_launch",
            0,
            0,
            0,
            0,
        ),
    ),
)
def test_advance_once_dispatches_exactly_one_reducer_action(
    monkeypatch: pytest.MonkeyPatch,
    action: OnlyAgentNextActionV1,
    expected_materializer: str | None,
    model_io: int,
    tool_io: int,
    model_recovery: int,
    tool_recovery: int,
) -> None:
    reducer = _Reducer(action)
    materializer = _Materializer()
    models = _Models()
    tools = _Tools()
    calls = {"model": 0, "tool": 0}
    manifest = SimpleNamespace(implementation_fingerprint="4" * 64, source_revision="5" * 40)
    permit = SimpleNamespace(historical_workflow_resource_fingerprint="6" * 64)
    monkeypatch.setattr(driver_module, "build_current_agent_workflow_implementation_manifest", lambda: manifest)
    monkeypatch.setattr(driver_module, "assert_runtime_execution_permit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        driver_module,
        "execute_after_runtime_admission",
        lambda _session, _reader, continuation: continuation(permit),
    )
    monkeypatch.setattr(
        driver_module,
        "execute_external_model_occurrence",
        lambda **_kwargs: calls.__setitem__("model", calls["model"] + 1),
    )
    monkeypatch.setattr(
        driver_module,
        "execute_external_tool_occurrence",
        lambda **_kwargs: calls.__setitem__("tool", calls["tool"] + 1),
    )
    driver = OnlyAgentSessionDriverV1(
        reducer=reducer,  # type: ignore[arg-type]
        sessions=object(),  # type: ignore[arg-type]
        materializer=materializer,  # type: ignore[arg-type]
        model_occurrences=models,  # type: ignore[arg-type]
        tool_occurrences=tools,  # type: ignore[arg-type]
        model_adapter=object(),  # type: ignore[arg-type]
        product_adapter=object(),  # type: ignore[arg-type]
        coordination=_Coordinator(),  # type: ignore[arg-type]
    )
    state = driver.advance_once(SESSION)
    assert state.status is OnlyAgentDerivedSessionStatus.COMPLETE
    assert materializer.calls == ([] if expected_materializer is None else [expected_materializer])
    assert calls == {"model": model_io, "tool": tool_io}
    assert models.recoveries == model_recovery
    assert tools.recoveries == tool_recovery
    assert reducer.calls == 2


def test_terminal_advance_has_zero_admission_mutation_or_io(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = OnlyAgentDerivedSessionStateV1(SESSION, OnlyAgentDerivedSessionStatus.COMPLETE, None)
    reducer = SimpleNamespace(derive=lambda _session: terminal)
    admissions: list[str] = []
    monkeypatch.setattr(
        driver_module,
        "execute_after_runtime_admission",
        lambda session, _reader, continuation: (
            admissions.append(session),
            continuation(SimpleNamespace(historical_workflow_resource_fingerprint="6" * 64)),
        )[1],
    )
    driver = OnlyAgentSessionDriverV1(
        reducer=reducer,  # type: ignore[arg-type]
        sessions=object(),  # type: ignore[arg-type]
        materializer=object(),  # type: ignore[arg-type]
        model_occurrences=object(),  # type: ignore[arg-type]
        tool_occurrences=object(),  # type: ignore[arg-type]
        model_adapter=object(),  # type: ignore[arg-type]
        product_adapter=object(),  # type: ignore[arg-type]
        coordination=_Coordinator(),  # type: ignore[arg-type]
    )
    assert driver.advance_once(SESSION) == terminal
    assert admissions == [SESSION]


def test_runtime_mismatch_has_zero_materialization_or_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    action = OnlyAgentNextActionV1(OnlyAgentNextActionKind.PREPARE_MODEL_CALL, logical_role="RESEARCH_PLANNER")
    reducer = _Reducer(action)
    materializer = _Materializer()
    calls: list[str] = []

    def mismatch(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("AGENT_WORKFLOW_RUNTIME_MISMATCH")

    monkeypatch.setattr(driver_module, "execute_after_runtime_admission", mismatch)
    monkeypatch.setattr(driver_module, "execute_external_model_occurrence", lambda **_kwargs: calls.append("model"))
    monkeypatch.setattr(driver_module, "execute_external_tool_occurrence", lambda **_kwargs: calls.append("tool"))
    driver = OnlyAgentSessionDriverV1(
        reducer=reducer,  # type: ignore[arg-type]
        sessions=object(),  # type: ignore[arg-type]
        materializer=materializer,  # type: ignore[arg-type]
        model_occurrences=object(),  # type: ignore[arg-type]
        tool_occurrences=object(),  # type: ignore[arg-type]
        model_adapter=object(),  # type: ignore[arg-type]
        product_adapter=object(),  # type: ignore[arg-type]
        coordination=_Coordinator(),  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError, match="AGENT_WORKFLOW_RUNTIME_MISMATCH"):
        driver.advance_once(SESSION)
    assert reducer.calls == 0
    assert materializer.calls == []
    assert calls == []


def test_terminal_search_observation_matches_exact_product_projection_without_synthetic_owner() -> None:
    fact = SimpleNamespace(to_dict=lambda: {"feedback_decision_fingerprint": "7" * 64})
    terminal = SimpleNamespace(
        experiment_fingerprint="8" * 64,
        method=SimpleNamespace(value="PARAMETER"),
        terminal_kind=SimpleNamespace(value="TERMINAL_PARAMETER_STOP"),
        terminal_fact=fact,
        stop_reason="SEARCH_SPACE_EXHAUSTED",
    )
    response = {
        "schema_version": 1,
        "experiment_fingerprint": "8" * 64,
        "method": "PARAMETER",
        "terminal_kind": "TERMINAL_PARAMETER_STOP",
        "terminal_fact": fact.to_dict(),
        "stop_reason": "SEARCH_SPACE_EXHAUSTED",
    }
    result = SimpleNamespace(canonical_validated_response=response)
    assert OnlyAgentSessionReducerV1._terminal_search_response_matches(result, terminal)
    response["stop_reason"] = "DIFFERENT"
    assert not OnlyAgentSessionReducerV1._terminal_search_response_matches(result, terminal)
