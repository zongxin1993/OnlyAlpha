"""Transport-neutral Product adapters over the authoritative Search methods."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import NoReturn, Protocol, cast

from onlyalpha.application.product_command_authority import (
    OnlyProductCommandAdmissionAuthority,
    OnlyProductCommandAuthorityUnavailableError,
    OnlyProductCommandReceiptAuthority,
    only_verify_product_command_binding,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
    only_product_command_fingerprint,
)
from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority
from onlyalpha.kernel.command import OnlyProductCommand
from onlyalpha.kernel.query import OnlyProductQuery
from onlyalpha.research.experiment import (
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchExperimentManifestV2,
    OnlySearchExperimentManifestV3,
    OnlySearchHypothesisV1,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.experiment.model import OnlySearchExperimentManifest
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId


def _sha(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lower-case SHA-256")
    return value


def _non_negative(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


class OnlySearchProductError(RuntimeError):
    code = "SEARCH_PRODUCT_ERROR"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class OnlySearchProductCommandConflict(OnlySearchProductError):
    code = "SEARCH_PRODUCT_COMMAND_CONFLICT"


class OnlySearchProductExpectedStateMismatch(OnlySearchProductError):
    code = "SEARCH_PRODUCT_EXPECTED_STATE_MISMATCH"


class OnlySearchProductEffectConflict(OnlySearchProductError):
    code = "SEARCH_PRODUCT_EFFECT_CONFLICT"


class OnlySearchProductMethodUnsupported(OnlySearchProductError):
    code = "SEARCH_PRODUCT_METHOD_UNSUPPORTED"


class OnlySearchProductCapabilityUnsupported(OnlySearchProductError):
    code = "SEARCH_PRODUCT_CAPABILITY_UNSUPPORTED"


class OnlySearchProductReceiptCorrupt(OnlySearchProductError):
    code = "SEARCH_PRODUCT_RECEIPT_CORRUPT"


class OnlySearchProductSemanticFactCorrupt(OnlySearchProductError):
    code = "SEARCH_PRODUCT_SEMANTIC_FACT_CORRUPT"


class OnlySearchProductAuthorityUnavailable(OnlySearchProductError):
    code = "SEARCH_PRODUCT_AUTHORITY_UNAVAILABLE"


class OnlySearchRuntimeGenerationUnbound(OnlySearchProductError):
    code = "SEARCH_RUNTIME_GENERATION_UNBOUND"


class OnlySearchRuntimeGenerationBindingConflict(OnlySearchProductError):
    code = "SEARCH_RUNTIME_GENERATION_BINDING_CONFLICT"


class OnlySearchRuntimeGenerationNotFound(OnlySearchProductError):
    code = "SEARCH_RUNTIME_GENERATION_NOT_FOUND"


class OnlySearchRuntimeGenerationUnavailable(OnlySearchProductError):
    code = "SEARCH_RUNTIME_GENERATION_UNAVAILABLE"


class OnlySearchRuntimeGenerationInvalid(OnlySearchProductError):
    code = "SEARCH_RUNTIME_GENERATION_INVALID"


class OnlySearchRuntimeGenerationNotEligibleForNewWork(OnlySearchProductError):
    code = "SEARCH_RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK"


class OnlySearchRuntimeGenerationDerivedBindingConflict(OnlySearchProductError):
    code = "SEARCH_RUNTIME_GENERATION_DERIVED_BINDING_CONFLICT"


class OnlySearchMethodV1(StrEnum):
    SYMBOLIC = "SYMBOLIC"
    PARAMETER = "PARAMETER"


class OnlySearchBoundedOperationV1(StrEnum):
    ADVANCE_ONE_SYMBOLIC_OCCURRENCE = "ADVANCE_ONE_SYMBOLIC_OCCURRENCE"
    RECONCILE_ONE_SYMBOLIC_OCCURRENCE = "RECONCILE_ONE_SYMBOLIC_OCCURRENCE"
    ADVANCE_ONE_PARAMETER_DECISION = "ADVANCE_ONE_PARAMETER_DECISION"
    RECONCILE_OPEN_PARAMETER_BATCH = "RECONCILE_OPEN_PARAMETER_BATCH"

    @property
    def method(self) -> OnlySearchMethodV1:
        if self in {
            self.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
            self.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
        }:
            return OnlySearchMethodV1.SYMBOLIC
        return OnlySearchMethodV1.PARAMETER


class OnlySearchProductEffectStateV1(StrEnum):
    EXACT_PRE_STATE = "EXACT_PRE_STATE"
    PARTIAL_EXACT_EFFECT = "PARTIAL_EXACT_EFFECT"
    COMPLETE_EXACT_EFFECT = "COMPLETE_EXACT_EFFECT"
    CONFLICT_OR_STALE = "CONFLICT_OR_STALE"


class OnlySearchTerminalKindV1(StrEnum):
    NON_TERMINAL = "NON_TERMINAL"
    TERMINAL_SYMBOLIC_COMPLETION = "TERMINAL_SYMBOLIC_COMPLETION"
    TERMINAL_PARAMETER_STOP = "TERMINAL_PARAMETER_STOP"


@dataclass(frozen=True, slots=True)
class OnlySearchPlanExpectedStateV1:
    plan_fingerprint: str
    result_fingerprint: str | None = None
    research_product_command_id: str | None = None
    research_receipt_outcome_id: str | None = None

    def __post_init__(self) -> None:
        _sha(self.plan_fingerprint, "plan_fingerprint")
        if self.result_fingerprint is not None:
            _sha(self.result_fingerprint, "result_fingerprint")
        if (self.research_product_command_id is None) != (self.research_receipt_outcome_id is None):
            raise ValueError("Research Product Command and Receipt observations must be both present or both absent")
        if self.research_product_command_id is not None:
            OnlyProductCommandId(self.research_product_command_id)
            OnlyProductCommandOutcomeRef(
                OnlyProductCommandOutcomeKind.RESEARCH_RUN,
                cast(str, self.research_receipt_outcome_id),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_fingerprint": self.plan_fingerprint,
            "result_fingerprint": self.result_fingerprint,
            "research_product_command_id": self.research_product_command_id,
            "research_receipt_outcome_id": self.research_receipt_outcome_id,
        }


@dataclass(frozen=True, slots=True)
class OnlySymbolicExpectedStateV1:
    experiment_fingerprint: str
    enumeration_result_fingerprint: str | None
    ordered_plan_states: tuple[OnlySearchPlanExpectedStateV1, ...]
    next_iteration_ordinal: int
    research_attempt_count: int
    qualification_attempt_count: int
    target_plan_fingerprint: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("Symbolic expected-state schema is unsupported")
        _sha(self.experiment_fingerprint, "experiment_fingerprint")
        if self.enumeration_result_fingerprint is not None:
            _sha(self.enumeration_result_fingerprint, "enumeration_result_fingerprint")
        if not isinstance(self.ordered_plan_states, tuple) or any(
            not isinstance(item, OnlySearchPlanExpectedStateV1) for item in self.ordered_plan_states
        ):
            raise ValueError("Symbolic ordered Plan state must be a tuple")
        _non_negative(self.next_iteration_ordinal, "next_iteration_ordinal")
        _non_negative(self.research_attempt_count, "research_attempt_count")
        _non_negative(self.qualification_attempt_count, "qualification_attempt_count")
        if self.next_iteration_ordinal != len(self.ordered_plan_states):
            raise ValueError("Symbolic expected next ordinal must equal the contiguous Plan prefix length")
        if self.enumeration_result_fingerprint is None and self.ordered_plan_states:
            raise ValueError("Enumeration ABSENT is legal only before the first Symbolic Plan")
        if self.target_plan_fingerprint is not None:
            _sha(self.target_plan_fingerprint, "target_plan_fingerprint")
            if self.target_plan_fingerprint not in {item.plan_fingerprint for item in self.ordered_plan_states}:
                raise ValueError("Symbolic reconcile target must occur in the expected ledger")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "experiment_fingerprint": self.experiment_fingerprint,
            "enumeration_result_fingerprint": self.enumeration_result_fingerprint,
            "ordered_plan_states": [item.to_dict() for item in self.ordered_plan_states],
            "next_iteration_ordinal": self.next_iteration_ordinal,
            "research_attempt_count": self.research_attempt_count,
            "qualification_attempt_count": self.qualification_attempt_count,
            "target_plan_fingerprint": self.target_plan_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class OnlyParameterExpectedStateV1:
    experiment_fingerprint: str
    frontier_fingerprint: str | None
    ordered_feedback_decision_fingerprints: tuple[str, ...]
    frontier_plan_states: tuple[OnlySearchPlanExpectedStateV1, ...]
    proposal_count: int
    research_attempt_count: int
    qualification_attempt_count: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("Parameter expected-state schema is unsupported")
        _sha(self.experiment_fingerprint, "experiment_fingerprint")
        for value in self.ordered_feedback_decision_fingerprints:
            _sha(value, "feedback_decision_fingerprint")
        if (self.frontier_fingerprint is None) != (not self.ordered_feedback_decision_fingerprints):
            raise ValueError("Parameter frontier and Decision chain disagree")
        if self.frontier_fingerprint is not None:
            _sha(self.frontier_fingerprint, "frontier_fingerprint")
            if self.ordered_feedback_decision_fingerprints[-1] != self.frontier_fingerprint:
                raise ValueError("Parameter frontier must terminate its Decision chain")
        if not isinstance(self.frontier_plan_states, tuple) or any(
            not isinstance(item, OnlySearchPlanExpectedStateV1) for item in self.frontier_plan_states
        ):
            raise ValueError("Parameter frontier Plan state must be a tuple")
        for field, count in (
            ("proposal_count", self.proposal_count),
            ("research_attempt_count", self.research_attempt_count),
            ("qualification_attempt_count", self.qualification_attempt_count),
        ):
            _non_negative(count, field)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "experiment_fingerprint": self.experiment_fingerprint,
            "frontier_fingerprint": self.frontier_fingerprint,
            "ordered_feedback_decision_fingerprints": list(self.ordered_feedback_decision_fingerprints),
            "frontier_plan_states": [item.to_dict() for item in self.frontier_plan_states],
            "proposal_count": self.proposal_count,
            "research_attempt_count": self.research_attempt_count,
            "qualification_attempt_count": self.qualification_attempt_count,
        }


OnlySearchExpectedStateV1 = OnlySymbolicExpectedStateV1 | OnlyParameterExpectedStateV1


class _SearchSubmitIntent(Protocol):
    command_id: OnlyProductCommandId
    method: OnlySearchMethodV1

    @property
    def command_fingerprint(self) -> str: ...


def _resource_payload(value: object) -> object:
    serializer = getattr(value, "to_dict", None)
    if not callable(serializer):
        raise ValueError("Search Product immutable input lacks a canonical payload")
    payload = serializer()
    if not isinstance(payload, Mapping):
        raise ValueError("Search Product immutable input payload must be an object")
    return payload


@dataclass(frozen=True, slots=True)
class OnlySubmitSymbolicSearchExperimentV1(OnlyProductCommand):
    command_id: OnlyProductCommandId
    hypothesis: OnlySearchHypothesisV1
    search_space: object
    evaluation_contract: object
    search_budget: OnlySearchBudgetV1
    algorithm_manifest: object
    workflow_binding: OnlySearchWorkflowBindingV1
    decision_engine_binding: OnlySearchDecisionEngineBindingV1
    catalog_generation_fingerprint: str
    dataset_snapshot_fingerprint: str
    parent_experiment_fingerprint: str | None = None
    schema_version: int = 1

    method = OnlySearchMethodV1.SYMBOLIC

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.command_id, OnlyProductCommandId):
            raise ValueError("Symbolic Submit command is invalid")
        if not isinstance(self.hypothesis, OnlySearchHypothesisV1):
            raise ValueError("Symbolic Submit hypothesis is invalid")
        if not isinstance(self.search_budget, OnlySearchBudgetV1):
            raise ValueError("Symbolic Submit budget is invalid")
        if not isinstance(self.workflow_binding, OnlySearchWorkflowBindingV1):
            raise ValueError("Symbolic Submit workflow binding is invalid")
        if not isinstance(self.decision_engine_binding, OnlySearchDecisionEngineBindingV1):
            raise ValueError("Symbolic Submit decision binding is invalid")
        _sha(self.catalog_generation_fingerprint, "catalog_generation_fingerprint")
        _sha(self.dataset_snapshot_fingerprint, "dataset_snapshot_fingerprint")
        if self.parent_experiment_fingerprint is not None:
            _sha(self.parent_experiment_fingerprint, "parent_experiment_fingerprint")
        _resource_payload(self.search_space)
        _resource_payload(self.evaluation_contract)
        _resource_payload(self.algorithm_manifest)

    def intent_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "method": self.method.value,
            "hypothesis": self.hypothesis.to_dict(),
            "search_space": _resource_payload(self.search_space),
            "evaluation_contract": _resource_payload(self.evaluation_contract),
            "search_budget": self.search_budget.to_dict(),
            "algorithm_manifest": _resource_payload(self.algorithm_manifest),
            "workflow_binding": self.workflow_binding.to_dict(),
            "decision_engine_binding": self.decision_engine_binding.to_dict(),
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "parent_experiment_fingerprint": self.parent_experiment_fingerprint,
        }

    @property
    def command_fingerprint(self) -> str:
        return only_product_command_fingerprint(self.intent_dict())


@dataclass(frozen=True, slots=True)
class OnlySubmitParameterSearchExperimentV1(OnlyProductCommand):
    command_id: OnlyProductCommandId
    hypothesis: OnlySearchHypothesisV1
    search_space: object
    evaluation_contract: object
    search_policy: object
    search_budget: OnlySearchBudgetV1
    algorithm_manifest: object
    workflow_binding: OnlySearchWorkflowBindingV1
    decision_engine_binding: OnlySearchDecisionEngineBindingV1
    catalog_generation_fingerprint: str
    dataset_snapshot_fingerprint: str
    parent_experiment_fingerprint: str | None = None
    schema_version: int = 1

    method = OnlySearchMethodV1.PARAMETER

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.command_id, OnlyProductCommandId):
            raise ValueError("Parameter Submit command is invalid")
        if not isinstance(self.hypothesis, OnlySearchHypothesisV1):
            raise ValueError("Parameter Submit hypothesis is invalid")
        if not isinstance(self.search_budget, OnlySearchBudgetV1):
            raise ValueError("Parameter Submit budget is invalid")
        if not isinstance(self.workflow_binding, OnlySearchWorkflowBindingV1):
            raise ValueError("Parameter Submit workflow binding is invalid")
        if not isinstance(self.decision_engine_binding, OnlySearchDecisionEngineBindingV1):
            raise ValueError("Parameter Submit decision binding is invalid")
        _sha(self.catalog_generation_fingerprint, "catalog_generation_fingerprint")
        _sha(self.dataset_snapshot_fingerprint, "dataset_snapshot_fingerprint")
        if self.parent_experiment_fingerprint is not None:
            _sha(self.parent_experiment_fingerprint, "parent_experiment_fingerprint")
        for resource in (self.search_space, self.evaluation_contract, self.search_policy, self.algorithm_manifest):
            _resource_payload(resource)

    def intent_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "method": self.method.value,
            "hypothesis": self.hypothesis.to_dict(),
            "search_space": _resource_payload(self.search_space),
            "evaluation_contract": _resource_payload(self.evaluation_contract),
            "search_policy": _resource_payload(self.search_policy),
            "search_budget": self.search_budget.to_dict(),
            "algorithm_manifest": _resource_payload(self.algorithm_manifest),
            "workflow_binding": self.workflow_binding.to_dict(),
            "decision_engine_binding": self.decision_engine_binding.to_dict(),
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "parent_experiment_fingerprint": self.parent_experiment_fingerprint,
        }

    @property
    def command_fingerprint(self) -> str:
        return only_product_command_fingerprint(self.intent_dict())


@dataclass(frozen=True, slots=True)
class OnlySubmitSymbolicSearchExperimentV2(OnlySubmitSymbolicSearchExperimentV1):
    runtime_generation_fingerprint: str = ""
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version != 2 or not isinstance(self.command_id, OnlyProductCommandId):
            raise ValueError("Symbolic Submit V2 command is invalid")
        if not isinstance(self.hypothesis, OnlySearchHypothesisV1):
            raise ValueError("Symbolic Submit V2 hypothesis is invalid")
        if not isinstance(self.search_budget, OnlySearchBudgetV1):
            raise ValueError("Symbolic Submit V2 budget is invalid")
        if not isinstance(self.workflow_binding, OnlySearchWorkflowBindingV1):
            raise ValueError("Symbolic Submit V2 workflow binding is invalid")
        if not isinstance(self.decision_engine_binding, OnlySearchDecisionEngineBindingV1):
            raise ValueError("Symbolic Submit V2 decision binding is invalid")
        for value, field in (
            (self.catalog_generation_fingerprint, "catalog_generation_fingerprint"),
            (self.dataset_snapshot_fingerprint, "dataset_snapshot_fingerprint"),
            (self.runtime_generation_fingerprint, "runtime_generation_fingerprint"),
        ):
            _sha(value, field)
        if self.parent_experiment_fingerprint is not None:
            _sha(self.parent_experiment_fingerprint, "parent_experiment_fingerprint")
        _resource_payload(self.search_space)
        _resource_payload(self.evaluation_contract)
        _resource_payload(self.algorithm_manifest)

    def intent_dict(self) -> dict[str, object]:
        result = OnlySubmitSymbolicSearchExperimentV1.intent_dict(self)
        result["runtime_generation_fingerprint"] = self.runtime_generation_fingerprint
        return result


@dataclass(frozen=True, slots=True)
class OnlySubmitParameterSearchExperimentV2(OnlySubmitParameterSearchExperimentV1):
    runtime_generation_fingerprint: str = ""
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version != 2 or not isinstance(self.command_id, OnlyProductCommandId):
            raise ValueError("Parameter Submit V2 command is invalid")
        if not isinstance(self.hypothesis, OnlySearchHypothesisV1):
            raise ValueError("Parameter Submit V2 hypothesis is invalid")
        if not isinstance(self.search_budget, OnlySearchBudgetV1):
            raise ValueError("Parameter Submit V2 budget is invalid")
        if not isinstance(self.workflow_binding, OnlySearchWorkflowBindingV1):
            raise ValueError("Parameter Submit V2 workflow binding is invalid")
        if not isinstance(self.decision_engine_binding, OnlySearchDecisionEngineBindingV1):
            raise ValueError("Parameter Submit V2 decision binding is invalid")
        for value, field in (
            (self.catalog_generation_fingerprint, "catalog_generation_fingerprint"),
            (self.dataset_snapshot_fingerprint, "dataset_snapshot_fingerprint"),
            (self.runtime_generation_fingerprint, "runtime_generation_fingerprint"),
        ):
            _sha(value, field)
        if self.parent_experiment_fingerprint is not None:
            _sha(self.parent_experiment_fingerprint, "parent_experiment_fingerprint")
        for resource in (self.search_space, self.evaluation_contract, self.search_policy, self.algorithm_manifest):
            _resource_payload(resource)

    def intent_dict(self) -> dict[str, object]:
        result = OnlySubmitParameterSearchExperimentV1.intent_dict(self)
        result["runtime_generation_fingerprint"] = self.runtime_generation_fingerprint
        return result


OnlySearchSubmitCommandV1 = (
    OnlySubmitSymbolicSearchExperimentV1
    | OnlySubmitParameterSearchExperimentV1
    | OnlySubmitSymbolicSearchExperimentV2
    | OnlySubmitParameterSearchExperimentV2
)


def only_search_experiment_work_id(experiment_fingerprint: str) -> str:
    _sha(experiment_fingerprint, "experiment_fingerprint")
    return f"search-experiment:{experiment_fingerprint}"


@dataclass(frozen=True, slots=True)
class OnlyAdvanceSearchExperimentV1(OnlyProductCommand):
    command_id: OnlyProductCommandId
    method: OnlySearchMethodV1
    operation: OnlySearchBoundedOperationV1
    expected_state: OnlySearchExpectedStateV1
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.command_id, OnlyProductCommandId):
            raise ValueError("Search Advance command is invalid")
        if not isinstance(self.method, OnlySearchMethodV1) or not isinstance(
            self.operation, OnlySearchBoundedOperationV1
        ):
            raise ValueError("Search Advance discriminant is invalid")
        if self.operation.method is not self.method:
            raise ValueError("Search operation and method disagree")
        expected_type = (
            OnlySymbolicExpectedStateV1 if self.method is OnlySearchMethodV1.SYMBOLIC else OnlyParameterExpectedStateV1
        )
        if not isinstance(self.expected_state, expected_type):
            raise ValueError("Search method-specific expected state is invalid")

    @property
    def experiment_fingerprint(self) -> str:
        return self.expected_state.experiment_fingerprint

    def intent_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "method": self.method.value,
            "operation": self.operation.value,
            "expected_state": self.expected_state.to_dict(),
        }

    @property
    def command_fingerprint(self) -> str:
        return only_product_command_fingerprint(self.intent_dict())


@dataclass(frozen=True, slots=True)
class OnlyGetSearchExperimentV1(OnlyProductQuery):
    experiment_fingerprint: str

    def __post_init__(self) -> None:
        _sha(self.experiment_fingerprint, "experiment_fingerprint")


@dataclass(frozen=True, slots=True)
class OnlyGetSearchIterationLedgerV1(OnlyProductQuery):
    experiment_fingerprint: str

    def __post_init__(self) -> None:
        _sha(self.experiment_fingerprint, "experiment_fingerprint")


@dataclass(frozen=True, slots=True)
class OnlyGetSearchTerminalDecisionV1(OnlyProductQuery):
    experiment_fingerprint: str

    def __post_init__(self) -> None:
        _sha(self.experiment_fingerprint, "experiment_fingerprint")


@dataclass(frozen=True, slots=True)
class OnlySearchExperimentProjectionV1:
    method: OnlySearchMethodV1
    experiment: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3


@dataclass(frozen=True, slots=True)
class OnlySearchIterationLedgerProjectionV1:
    method: OnlySearchMethodV1
    experiment_fingerprint: str
    plans: tuple[OnlySearchIterationPlanV1, ...]
    results: tuple[OnlySearchIterationResultV1 | None, ...]
    expected_state: OnlySearchExpectedStateV1
    enumeration_result: object | None = None
    feedback_decisions: tuple[object, ...] = ()
    frontier_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class OnlySearchTerminalProjectionV1:
    method: OnlySearchMethodV1
    experiment_fingerprint: str
    terminal_kind: OnlySearchTerminalKindV1
    terminal_fact: object | None = None
    stop_reason: str | None = None


@dataclass(frozen=True, slots=True)
class OnlySearchProductOutcomeV1:
    receipt: OnlyProductCommandReceipt
    experiment: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3
    ledger: OnlySearchIterationLedgerProjectionV1
    terminal: OnlySearchTerminalProjectionV1
    replayed: bool


class OnlySearchProductMethodAdapter(Protocol):
    method: OnlySearchMethodV1

    def derive_submit_experiment(self, command: OnlySearchSubmitCommandV1) -> OnlySearchExperimentManifest: ...

    def commit_submit(
        self,
        command: OnlySearchSubmitCommandV1,
        experiment: OnlySearchExperimentManifest,
    ) -> OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3: ...

    def load_experiment_verified(
        self, experiment_fingerprint: str
    ) -> OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3: ...

    def verify_submit(
        self,
        command: OnlySearchSubmitCommandV1,
        experiment: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3,
    ) -> None: ...

    def apply_advance(self, command: OnlyAdvanceSearchExperimentV1) -> None: ...

    def assess_advance_effect(self, command: OnlyAdvanceSearchExperimentV1) -> OnlySearchProductEffectStateV1: ...

    def verify_advance_effect(self, command: OnlyAdvanceSearchExperimentV1) -> None: ...

    def ledger(self, experiment_fingerprint: str) -> OnlySearchIterationLedgerProjectionV1: ...

    def terminal(self, experiment_fingerprint: str) -> OnlySearchTerminalProjectionV1: ...


class OnlySearchProductQueryServiceV1:
    def __init__(self, adapters: tuple[OnlySearchProductMethodAdapter, ...]) -> None:
        self._adapters = _adapter_map(adapters)

    def get_experiment(self, query: OnlyGetSearchExperimentV1) -> OnlySearchExperimentProjectionV1:
        method, adapter, experiment = self._locate(query.experiment_fingerprint)
        return OnlySearchExperimentProjectionV1(method, experiment)

    def get_ledger(self, query: OnlyGetSearchIterationLedgerV1) -> OnlySearchIterationLedgerProjectionV1:
        _method, adapter, _experiment = self._locate(query.experiment_fingerprint)
        return adapter.ledger(query.experiment_fingerprint)

    def get_terminal(self, query: OnlyGetSearchTerminalDecisionV1) -> OnlySearchTerminalProjectionV1:
        _method, adapter, _experiment = self._locate(query.experiment_fingerprint)
        return adapter.terminal(query.experiment_fingerprint)

    def _locate(
        self, experiment_fingerprint: str
    ) -> tuple[
        OnlySearchMethodV1,
        OnlySearchProductMethodAdapter,
        OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3,
    ]:
        found: list[
            tuple[
                OnlySearchMethodV1,
                OnlySearchProductMethodAdapter,
                OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3,
            ]
        ] = []
        for method, adapter in self._adapters.items():
            try:
                found.append((method, adapter, adapter.load_experiment_verified(experiment_fingerprint)))
            except Exception as exc:
                if _is_not_found(exc) or isinstance(exc, OnlySearchProductMethodUnsupported):
                    continue
                raise
        if len(found) != 1:
            raise OnlySearchProductSemanticFactCorrupt(experiment_fingerprint)
        return found[0]


class OnlySearchProductCommandServiceV1:
    """Admission/Receipt orchestration that owns no Search method semantics."""

    def __init__(
        self,
        *,
        command_admissions: OnlyProductCommandAdmissionAuthority,
        command_receipts: OnlyProductCommandReceiptAuthority,
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
        adapters: tuple[OnlySearchProductMethodAdapter, ...],
        now_utc: Callable[[], datetime],
    ) -> None:
        self._admissions = command_admissions
        self._receipts = command_receipts
        self._runtime_generations = runtime_generations
        self._adapters = _adapter_map(adapters)
        self._now_utc = now_utc

    def submit(self, command: OnlySearchSubmitCommandV1) -> OnlySearchProductOutcomeV1:
        adapter = self._adapter(command.method)
        expected = adapter.derive_submit_experiment(command)
        kind = (
            OnlyProductCommandKind.CREATE_SYMBOLIC_SEARCH_EXPERIMENT
            if command.method is OnlySearchMethodV1.SYMBOLIC
            else OnlyProductCommandKind.CREATE_PARAMETER_SEARCH_EXPERIMENT
        )
        existing_admission = self._load_admission(command.command_id)
        if isinstance(command, (OnlySubmitSymbolicSearchExperimentV2, OnlySubmitParameterSearchExperimentV2)):
            if existing_admission is None:
                manifest = self._require_new_work_generation(command.runtime_generation_fingerprint)
                self._require_manifest_match(
                    manifest,
                    command.runtime_generation_fingerprint,
                    command.catalog_generation_fingerprint,
                )
            admission = self._admit(command.command_id, kind, command.command_fingerprint)
            manifest = self._require_runtime_generation(command.runtime_generation_fingerprint)
            self._require_manifest_match(
                manifest,
                command.runtime_generation_fingerprint,
                command.catalog_generation_fingerprint,
            )
            self._bind_search_exact(expected.experiment_fingerprint, command.runtime_generation_fingerprint)
        else:
            if existing_admission is None:
                raise OnlySearchRuntimeGenerationUnbound("Search Submit V1 cannot admit new executable work")
            admission = self._admit(command.command_id, kind, command.command_fingerprint)
            self._require_search_binding(expected.experiment_fingerprint)
        receipt = self._load_receipt(admission)
        if receipt is not None:
            experiment = self._verify_receipt(adapter, command, expected.experiment_fingerprint, admission, receipt)
            return self._response(adapter, receipt, experiment, replayed=True)
        experiment = adapter.commit_submit(command, expected)
        adapter.verify_submit(command, experiment)
        if experiment.experiment_fingerprint != expected.experiment_fingerprint:
            raise OnlySearchProductSemanticFactCorrupt(experiment.experiment_fingerprint)
        receipt = self._put_receipt(admission, experiment.experiment_fingerprint)
        return self._response(adapter, receipt, experiment, replayed=False)

    def advance(self, command: OnlyAdvanceSearchExperimentV1) -> OnlySearchProductOutcomeV1:
        adapter = self._adapter(command.method)
        self._require_search_binding(command.experiment_fingerprint)
        admission = self._admit(
            command.command_id,
            OnlyProductCommandKind.ADVANCE_SEARCH_EXPERIMENT,
            command.command_fingerprint,
        )
        receipt = self._load_receipt(admission)
        if receipt is not None:
            experiment = self._verify_advance_receipt(adapter, command, admission, receipt)
            return self._response(adapter, receipt, experiment, replayed=True)
        experiment = adapter.load_experiment_verified(command.experiment_fingerprint)
        assessment = adapter.assess_advance_effect(command)
        if assessment is OnlySearchProductEffectStateV1.CONFLICT_OR_STALE:
            raise OnlySearchProductEffectConflict(command.experiment_fingerprint)
        if assessment in {
            OnlySearchProductEffectStateV1.EXACT_PRE_STATE,
            OnlySearchProductEffectStateV1.PARTIAL_EXACT_EFFECT,
        }:
            adapter.apply_advance(command)
        adapter.verify_advance_effect(command)
        exact = adapter.load_experiment_verified(experiment.experiment_fingerprint)
        receipt = self._put_receipt(admission, exact.experiment_fingerprint)
        return self._response(adapter, receipt, exact, replayed=False)

    def _load_admission(self, command_id: OnlyProductCommandId) -> OnlyProductCommandAdmissionV1 | None:
        try:
            return self._admissions.load_admission(command_id)
        except Exception as exc:
            if isinstance(exc, OnlyProductCommandAuthorityUnavailableError) or getattr(exc, "code", "") == (
                "PRODUCT_COMMAND_AUTHORITY_UNAVAILABLE"
            ):
                raise OnlySearchProductAuthorityUnavailable(command_id.value) from exc
            raise OnlySearchProductReceiptCorrupt(command_id.value) from exc

    def _require_new_work_generation(self, generation_fingerprint: str) -> object:
        try:
            return self._runtime_generations.require_new_work_generation(generation_fingerprint)
        except Exception as exc:
            self._raise_runtime_generation_error(exc, generation_fingerprint)

    def _bind_search_exact(self, experiment_fingerprint: str, generation_fingerprint: str) -> object:
        work_id = only_search_experiment_work_id(experiment_fingerprint)
        try:
            binding = self._runtime_generations.bind_work_exact(
                work_id,
                generation_fingerprint,
                actor="search-product-admission",
                occurred_at=self._now(),
            )
        except Exception as exc:
            self._raise_runtime_generation_error(exc, experiment_fingerprint)
        if (
            getattr(binding, "work_id", None) != work_id
            or getattr(binding, "runtime_generation_fingerprint", None) != generation_fingerprint
            or getattr(binding, "active", None) is not True
        ):
            raise OnlySearchRuntimeGenerationInvalid(experiment_fingerprint)
        return binding

    def _require_runtime_generation(self, generation_fingerprint: str) -> object:
        try:
            return self._runtime_generations.require_runtime_generation(generation_fingerprint)
        except Exception as exc:
            self._raise_runtime_generation_error(exc, generation_fingerprint)

    def _require_search_binding(self, experiment_fingerprint: str) -> object:
        try:
            binding = self._runtime_generations.require_work_binding(
                only_search_experiment_work_id(experiment_fingerprint)
            )
        except Exception as exc:
            self._raise_runtime_generation_error(exc, experiment_fingerprint)
        if getattr(binding, "active", True) is not True:
            raise OnlySearchRuntimeGenerationUnbound(experiment_fingerprint)
        return binding

    @staticmethod
    def _require_manifest_match(
        manifest: object,
        generation_fingerprint: str,
        catalog_fingerprint: str,
    ) -> None:
        if (
            getattr(manifest, "runtime_generation_fingerprint", None) != generation_fingerprint
            or getattr(manifest, "catalog_generation_fingerprint", None) != catalog_fingerprint
        ):
            raise OnlySearchRuntimeGenerationInvalid(generation_fingerprint)

    def _now(self) -> datetime:
        value = self._now_utc()
        if not isinstance(value, datetime):
            raise OnlySearchProductAuthorityUnavailable("now_utc returned a non-datetime value")
        return value

    @staticmethod
    def _raise_runtime_generation_error(exc: Exception, detail: str) -> NoReturn:
        code = str(exc)
        mapping: dict[str, type[OnlySearchProductError]] = {
            "RUNTIME_WORK_GENERATION_UNBOUND": OnlySearchRuntimeGenerationUnbound,
            "RUNTIME_DERIVED_PARENT_GENERATION_UNBOUND": OnlySearchRuntimeGenerationUnbound,
            "RUNTIME_WORK_GENERATION_BINDING_CONFLICT": OnlySearchRuntimeGenerationBindingConflict,
            "RUNTIME_DERIVED_WORK_GENERATION_BINDING_CONFLICT": OnlySearchRuntimeGenerationDerivedBindingConflict,
            "RUNTIME_GENERATION_NOT_FOUND": OnlySearchRuntimeGenerationNotFound,
            "RUNTIME_GENERATION_UNAVAILABLE": OnlySearchRuntimeGenerationUnavailable,
            "RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK": OnlySearchRuntimeGenerationNotEligibleForNewWork,
            "RUNTIME_GENERATION_VALIDATION_EVIDENCE_MISMATCH": OnlySearchRuntimeGenerationInvalid,
            "RUNTIME_GENERATION_MANIFEST_MISMATCH": OnlySearchRuntimeGenerationInvalid,
        }
        error_type = mapping.get(code, OnlySearchRuntimeGenerationInvalid)
        raise error_type(detail) from exc

    def _adapter(self, method: OnlySearchMethodV1) -> OnlySearchProductMethodAdapter:
        try:
            return self._adapters[method]
        except KeyError as exc:
            raise OnlySearchProductMethodUnsupported(method.value) from exc

    def _admit(
        self,
        command_id: OnlyProductCommandId,
        kind: OnlyProductCommandKind,
        fingerprint: str,
    ) -> OnlyProductCommandAdmissionV1:
        requested = OnlyProductCommandAdmissionV1(command_id, kind, fingerprint)
        try:
            self._admissions.admit_exact(requested)
            actual = self._admissions.load_admission(command_id)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if code == "PRODUCT_COMMAND_CONFLICT":
                raise OnlySearchProductCommandConflict(command_id.value) from exc
            if isinstance(exc, OnlyProductCommandAuthorityUnavailableError) or code == (
                "PRODUCT_COMMAND_AUTHORITY_UNAVAILABLE"
            ):
                raise OnlySearchProductAuthorityUnavailable(command_id.value) from exc
            if code in {"PRODUCT_COMMAND_ADMISSION_CORRUPT", "PRODUCT_COMMAND_BINDING_MISMATCH"}:
                raise OnlySearchProductReceiptCorrupt(command_id.value) from exc
            raise
        if actual != requested:
            raise OnlySearchProductCommandConflict(command_id.value)
        return requested

    def _load_receipt(self, admission: OnlyProductCommandAdmissionV1) -> OnlyProductCommandReceipt | None:
        try:
            receipt = self._receipts.load_verified_receipt(admission.command_id)
        except Exception as exc:
            raise OnlySearchProductReceiptCorrupt(admission.command_id.value) from exc
        if receipt is not None:
            try:
                only_verify_product_command_binding(admission, receipt)
            except Exception as exc:
                raise OnlySearchProductReceiptCorrupt(admission.command_id.value) from exc
        return receipt

    def _put_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        experiment_fingerprint: str,
    ) -> OnlyProductCommandReceipt:
        accepted_at = self._now_utc()
        if not isinstance(accepted_at, datetime):
            raise OnlySearchProductAuthorityUnavailable("now_utc returned a non-datetime value")
        requested = OnlyProductCommandReceipt(
            admission.command_id,
            admission.command_kind,
            admission.command_fingerprint,
            OnlyProductCommandOutcomeRef(
                OnlyProductCommandOutcomeKind.SEARCH_EXPERIMENT,
                experiment_fingerprint,
            ),
            accepted_at,
        )
        try:
            self._receipts.put_verified_receipt(requested)
            actual = self._receipts.load_verified_receipt(admission.command_id)
        except Exception as exc:
            raise OnlySearchProductReceiptCorrupt(admission.command_id.value) from exc
        if actual is None:
            raise OnlySearchProductReceiptCorrupt(admission.command_id.value)
        try:
            only_verify_product_command_binding(admission, actual)
        except Exception as exc:
            raise OnlySearchProductReceiptCorrupt(admission.command_id.value) from exc
        if actual.outcome_ref != requested.outcome_ref:
            raise OnlySearchProductReceiptCorrupt(admission.command_id.value)
        return actual

    def _verify_receipt(
        self,
        adapter: OnlySearchProductMethodAdapter,
        command: OnlySearchSubmitCommandV1,
        experiment_fingerprint: str,
        admission: OnlyProductCommandAdmissionV1,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3:
        del admission
        if (
            receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.SEARCH_EXPERIMENT
            or receipt.outcome_ref.outcome_id != experiment_fingerprint
        ):
            raise OnlySearchProductReceiptCorrupt(receipt.command_id.value)
        experiment = adapter.load_experiment_verified(experiment_fingerprint)
        adapter.verify_submit(command, experiment)
        return experiment

    def _verify_advance_receipt(
        self,
        adapter: OnlySearchProductMethodAdapter,
        command: OnlyAdvanceSearchExperimentV1,
        admission: OnlyProductCommandAdmissionV1,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3:
        del admission
        if (
            receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.SEARCH_EXPERIMENT
            or receipt.outcome_ref.outcome_id != command.experiment_fingerprint
        ):
            raise OnlySearchProductReceiptCorrupt(receipt.command_id.value)
        experiment = adapter.load_experiment_verified(command.experiment_fingerprint)
        # Receipt replay is proof-only and must execute zero Search/Research work.
        adapter.verify_advance_effect(command)
        return experiment

    @staticmethod
    def _response(
        adapter: OnlySearchProductMethodAdapter,
        receipt: OnlyProductCommandReceipt,
        experiment: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3,
        *,
        replayed: bool,
    ) -> OnlySearchProductOutcomeV1:
        return OnlySearchProductOutcomeV1(
            receipt,
            experiment,
            adapter.ledger(experiment.experiment_fingerprint),
            adapter.terminal(experiment.experiment_fingerprint),
            replayed,
        )


def _adapter_map(
    adapters: tuple[OnlySearchProductMethodAdapter, ...],
) -> Mapping[OnlySearchMethodV1, OnlySearchProductMethodAdapter]:
    if not isinstance(adapters, tuple):
        raise TypeError("Search Product adapters must be a frozen tuple")
    values: dict[OnlySearchMethodV1, OnlySearchProductMethodAdapter] = {}
    for adapter in adapters:
        if not isinstance(adapter.method, OnlySearchMethodV1) or adapter.method in values:
            raise ValueError("Search Product method adapter set is invalid")
        values[adapter.method] = adapter
    return MappingProxyType(values)


class OnlySearchResearchRunReader(Protocol):
    """Transport-neutral exact reader for the owning Research Run Authority."""

    def get_run(self, run_id: OnlyResearchRunId) -> OnlyResearchRun: ...


def only_load_search_research_run_exact(
    *,
    command_id: OnlyProductCommandId,
    receipts: OnlyProductCommandReceiptAuthority,
    runs: OnlySearchResearchRunReader,
    expected_specification: object | None = None,
) -> OnlyResearchRun | None:
    """Resolve a verified Product Receipt through the owning Research Run Authority."""

    receipt = receipts.load_verified_receipt(command_id)
    if receipt is None:
        return None
    if receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN:
        raise OnlySearchProductSemanticFactCorrupt(command_id.value)
    try:
        expected_id = OnlyResearchRunId(receipt.outcome_ref.outcome_id)
        loaded = runs.get_run(expected_id)
    except Exception as exc:
        raise OnlySearchProductSemanticFactCorrupt(receipt.outcome_ref.outcome_id) from exc
    if not isinstance(loaded, OnlyResearchRun) or loaded.run_id != expected_id:
        raise OnlySearchProductSemanticFactCorrupt(receipt.outcome_ref.outcome_id)
    if expected_specification is not None and loaded.specification != expected_specification:
        raise OnlySearchProductSemanticFactCorrupt(receipt.outcome_ref.outcome_id)
    return loaded


def _is_not_found(exc: Exception) -> bool:
    return getattr(exc, "code", None) == "SEARCH_EXPERIMENT_NOT_FOUND"


__all__ = [name for name in globals() if name.startswith("Only")]
