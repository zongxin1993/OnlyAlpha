"""Typed HTTP projection over the transport-neutral Search Product boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC
from typing import cast

from pydantic import JsonValue

from onlyalpha.application.product_boundary import OnlyResearchProductBoundary
from onlyalpha.application.product_command_receipt import OnlyProductCommandId, OnlyProductCommandReceipt
from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlyGetSearchExperimentV1,
    OnlyGetSearchIterationLedgerV1,
    OnlyGetSearchTerminalDecisionV1,
    OnlyParameterExpectedStateV1,
    OnlySearchBoundedOperationV1,
    OnlySearchExperimentProjectionV1,
    OnlySearchIterationLedgerProjectionV1,
    OnlySearchMethodV1,
    OnlySearchPlanExpectedStateV1,
    OnlySearchProductOutcomeV1,
    OnlySearchTerminalProjectionV1,
    OnlySubmitParameterSearchExperimentV2,
    OnlySubmitSymbolicSearchExperimentV2,
    OnlySymbolicExpectedStateV1,
)
from onlyalpha.research.experiment.model import (
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchHypothesisV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.search.parameter.model import (
    OnlyParameterFactorSearchSpaceV1,
    OnlyParameterSearchAlgorithmManifestV1,
    OnlyParameterSearchPolicyV1,
)
from onlyalpha.research.search.symbolic.algorithm import OnlySymbolicSearchAlgorithmImplementationManifestV1
from onlyalpha.research.search.symbolic.evaluation import OnlySymbolicResearchEvaluationContractV1
from onlyalpha.research.search.symbolic.model import OnlySymbolicFactorSearchSpaceV2

from .schema import (
    ParameterSearchSubmitRequestDto,
    SearchAdvanceRequestDto,
    SearchCommandResponseDto,
    SearchExperimentResponseDto,
    SearchLedgerResponseDto,
    SearchTerminalResponseDto,
    SymbolicSearchSubmitRequestDto,
)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"SEARCH_HTTP_{field.upper()}_INVALID")
    return cast(Mapping[str, object], value)


def _sequence(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"SEARCH_HTTP_{field.upper()}_INVALID")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"SEARCH_HTTP_{field.upper()}_INVALID")
    return value


def _plan_state(value: object) -> OnlySearchPlanExpectedStateV1:
    payload = _mapping(value, "plan_state")
    if set(payload) != {
        "plan_fingerprint",
        "result_fingerprint",
        "research_product_command_id",
        "research_receipt_outcome_id",
    }:
        raise ValueError("SEARCH_HTTP_PLAN_STATE_INVALID")
    return OnlySearchPlanExpectedStateV1(
        cast(str, payload["plan_fingerprint"]),
        _optional_string(payload["result_fingerprint"], "result_fingerprint"),
        _optional_string(payload["research_product_command_id"], "research_product_command_id"),
        _optional_string(payload["research_receipt_outcome_id"], "research_receipt_outcome_id"),
    )


def _expected_state(
    method: OnlySearchMethodV1,
    value: Mapping[str, object],
) -> OnlySymbolicExpectedStateV1 | OnlyParameterExpectedStateV1:
    if method is OnlySearchMethodV1.SYMBOLIC:
        return OnlySymbolicExpectedStateV1(
            cast(str, value["experiment_fingerprint"]),
            _optional_string(value["enumeration_result_fingerprint"], "enumeration_result_fingerprint"),
            tuple(_plan_state(item) for item in _sequence(value["ordered_plan_states"], "ordered_plan_states")),
            cast(int, value["next_iteration_ordinal"]),
            cast(int, value["research_attempt_count"]),
            cast(int, value["qualification_attempt_count"]),
            _optional_string(value.get("target_plan_fingerprint"), "target_plan_fingerprint"),
            cast(int, value["schema_version"]),
        )
    return OnlyParameterExpectedStateV1(
        cast(str, value["experiment_fingerprint"]),
        _optional_string(value["frontier_fingerprint"], "frontier_fingerprint"),
        tuple(cast(str, item) for item in _sequence(value["ordered_feedback_decision_fingerprints"], "decisions")),
        tuple(_plan_state(item) for item in _sequence(value["frontier_plan_states"], "frontier_plan_states")),
        cast(int, value["proposal_count"]),
        cast(int, value["research_attempt_count"]),
        cast(int, value["qualification_attempt_count"]),
        cast(int, value["schema_version"]),
    )


def _serialized(value: object | None) -> object | None:
    if value is None:
        return None
    serializer = getattr(value, "to_dict", None)
    if callable(serializer):
        return cast(object, serializer())
    raise ValueError("SEARCH_HTTP_PROJECTION_INVALID")


def _receipt(value: OnlyProductCommandReceipt) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "command_id": value.command_id.value,
        "command_kind": value.command_kind.value,
        "command_fingerprint": value.command_fingerprint,
        "outcome_ref": {"kind": value.outcome_ref.kind.value, "outcome_id": value.outcome_ref.outcome_id},
        "accepted_at": value.accepted_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }


def _ledger(value: OnlySearchIterationLedgerProjectionV1) -> dict[str, object]:
    return {
        "method": value.method.value,
        "experiment_fingerprint": value.experiment_fingerprint,
        "plans": [_serialized(item) for item in value.plans],
        "results": [_serialized(item) for item in value.results],
        "expected_state": value.expected_state.to_dict(),
        "enumeration_result": _serialized(value.enumeration_result),
        "feedback_decisions": [_serialized(item) for item in value.feedback_decisions],
        "frontier_fingerprint": value.frontier_fingerprint,
    }


def _terminal(value: OnlySearchTerminalProjectionV1) -> dict[str, object]:
    return {
        "method": value.method.value,
        "experiment_fingerprint": value.experiment_fingerprint,
        "terminal_kind": value.terminal_kind.value,
        "terminal_fact": _serialized(value.terminal_fact),
        "stop_reason": value.stop_reason,
    }


class OnlySearchProductHttpServiceV1:
    """No Store/DB access: dispatches typed commands and projects owning facts only."""

    def __init__(self, product: OnlyResearchProductBoundary) -> None:
        self._product = product

    def submit_symbolic(
        self, product_command_id: str, request: SymbolicSearchSubmitRequestDto
    ) -> SearchCommandResponseDto:
        payload = request.model_dump(mode="python")
        command = OnlySubmitSymbolicSearchExperimentV2(
            OnlyProductCommandId(product_command_id),
            OnlySearchHypothesisV1.from_dict(_mapping(payload["hypothesis"], "hypothesis")),
            OnlySymbolicFactorSearchSpaceV2.from_dict(_mapping(payload["search_space"], "search_space")),
            OnlySymbolicResearchEvaluationContractV1.from_dict(
                _mapping(payload["evaluation_contract"], "evaluation_contract")
            ),
            OnlySearchBudgetV1.from_dict(_mapping(payload["search_budget"], "search_budget")),
            OnlySymbolicSearchAlgorithmImplementationManifestV1.from_dict(
                _mapping(payload["algorithm_manifest"], "algorithm_manifest")
            ),
            OnlySearchWorkflowBindingV1.from_dict(_mapping(payload["workflow_binding"], "workflow_binding")),
            OnlySearchDecisionEngineBindingV1.from_dict(
                _mapping(payload["decision_engine_binding"], "decision_engine_binding")
            ),
            cast(str, payload["catalog_generation_fingerprint"]),
            cast(str, payload["dataset_snapshot_fingerprint"]),
            _optional_string(payload["parent_experiment_fingerprint"], "parent_experiment_fingerprint"),
            runtime_generation_fingerprint=cast(str, payload["runtime_generation_fingerprint"]),
        )
        return self._command(self._product.commands.dispatch(command))

    def submit_parameter(
        self, product_command_id: str, request: ParameterSearchSubmitRequestDto
    ) -> SearchCommandResponseDto:
        payload = request.model_dump(mode="python")
        command = OnlySubmitParameterSearchExperimentV2(
            OnlyProductCommandId(product_command_id),
            OnlySearchHypothesisV1.from_dict(_mapping(payload["hypothesis"], "hypothesis")),
            OnlyParameterFactorSearchSpaceV1.from_dict(_mapping(payload["search_space"], "search_space")),
            OnlySymbolicResearchEvaluationContractV1.from_dict(
                _mapping(payload["evaluation_contract"], "evaluation_contract")
            ),
            OnlyParameterSearchPolicyV1.from_dict(_mapping(payload["search_policy"], "search_policy")),
            OnlySearchBudgetV1.from_dict(_mapping(payload["search_budget"], "search_budget")),
            OnlyParameterSearchAlgorithmManifestV1.from_dict(
                _mapping(payload["algorithm_manifest"], "algorithm_manifest")
            ),
            OnlySearchWorkflowBindingV1.from_dict(_mapping(payload["workflow_binding"], "workflow_binding")),
            OnlySearchDecisionEngineBindingV1.from_dict(
                _mapping(payload["decision_engine_binding"], "decision_engine_binding")
            ),
            cast(str, payload["catalog_generation_fingerprint"]),
            cast(str, payload["dataset_snapshot_fingerprint"]),
            _optional_string(payload["parent_experiment_fingerprint"], "parent_experiment_fingerprint"),
            runtime_generation_fingerprint=cast(str, payload["runtime_generation_fingerprint"]),
        )
        return self._command(self._product.commands.dispatch(command))

    def advance_symbolic(self, product_command_id: str, request: SearchAdvanceRequestDto) -> SearchCommandResponseDto:
        return self._advance(product_command_id, request, OnlySearchMethodV1.SYMBOLIC)

    def advance_parameter(self, product_command_id: str, request: SearchAdvanceRequestDto) -> SearchCommandResponseDto:
        return self._advance(product_command_id, request, OnlySearchMethodV1.PARAMETER)

    def _advance(
        self,
        product_command_id: str,
        request: SearchAdvanceRequestDto,
        expected_method: OnlySearchMethodV1,
    ) -> SearchCommandResponseDto:
        payload = request.model_dump(mode="python")
        method = OnlySearchMethodV1(cast(str, payload["method"]))
        if method is not expected_method:
            raise ValueError("SEARCH_HTTP_METHOD_MISMATCH")
        state = _expected_state(method, _mapping(payload["expected_state"], "expected_state"))
        if state.experiment_fingerprint != payload["experiment_fingerprint"]:
            raise ValueError("SEARCH_HTTP_EXPERIMENT_IDENTITY_MISMATCH")
        command = OnlyAdvanceSearchExperimentV1(
            OnlyProductCommandId(product_command_id),
            method,
            OnlySearchBoundedOperationV1(cast(str, payload["operation"])),
            state,
        )
        return self._command(self._product.commands.dispatch(command))

    def get_experiment(self, experiment_fingerprint: str) -> SearchExperimentResponseDto:
        value = self._expected(
            self._product.queries.dispatch(OnlyGetSearchExperimentV1(experiment_fingerprint)),
            OnlySearchExperimentProjectionV1,
        )
        return SearchExperimentResponseDto(
            experiment_fingerprint=experiment_fingerprint,
            method=value.method.value,
            experiment=cast(dict[str, JsonValue], _serialized(value.experiment)),
        )

    def get_ledger(self, experiment_fingerprint: str) -> SearchLedgerResponseDto:
        value = self._expected(
            self._product.queries.dispatch(OnlyGetSearchIterationLedgerV1(experiment_fingerprint)),
            OnlySearchIterationLedgerProjectionV1,
        )
        return SearchLedgerResponseDto(
            experiment_fingerprint=experiment_fingerprint,
            method=value.method.value,
            ledger=cast(dict[str, JsonValue], _ledger(value)),
        )

    def get_terminal(self, experiment_fingerprint: str) -> SearchTerminalResponseDto:
        value = self._expected(
            self._product.queries.dispatch(OnlyGetSearchTerminalDecisionV1(experiment_fingerprint)),
            OnlySearchTerminalProjectionV1,
        )
        return SearchTerminalResponseDto(
            experiment_fingerprint=experiment_fingerprint,
            method=value.method.value,
            terminal_kind=value.terminal_kind.value,
            terminal_fact=cast(dict[str, JsonValue] | None, _serialized(value.terminal_fact)),
            stop_reason=value.stop_reason,
        )

    @staticmethod
    def _expected[ResultT](value: object, kind: type[ResultT]) -> ResultT:
        if not isinstance(value, kind):
            raise TypeError("SEARCH_HTTP_PRODUCT_RESULT_INVALID")
        return value

    @classmethod
    def _command(cls, value: object) -> SearchCommandResponseDto:
        outcome = cls._expected(value, OnlySearchProductOutcomeV1)
        return SearchCommandResponseDto(
            product_command_id=outcome.receipt.command_id.value,
            experiment_fingerprint=outcome.experiment.experiment_fingerprint,
            method=outcome.ledger.method.value,
            receipt=cast(dict[str, JsonValue], _receipt(outcome.receipt)),
            ledger=cast(dict[str, JsonValue], _ledger(outcome.ledger)),
            terminal=cast(dict[str, JsonValue], _terminal(outcome.terminal)),
            replayed=outcome.replayed,
        )


__all__ = ["OnlySearchProductHttpServiceV1"]
