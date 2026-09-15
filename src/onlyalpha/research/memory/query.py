"""Revision-bound deterministic reads over immutable Experiment Memory projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, cast
from uuid import UUID

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.run.model import OnlyResearchRunFailurePhase, OnlyResearchRunState

from .projector import OnlyMemoryProjectionRecordV1, OnlyMemorySourceRefV1
from .source_manifest import OnlyMemoryProjectionError
from .store import OnlyExperimentMemoryRevisionStore

QUERY_SCHEMA_VERSION = 3


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")
    return value


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_uuid4(value: object) -> bool:
    try:
        parsed = UUID(value)  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError):
        return False
    return parsed.version == 4 and str(parsed) == value


def _uuid4(value: object, name: str) -> str:
    if not _is_uuid4(value):
        raise ValueError(f"{name} must be a canonical UUID4")
    return cast(str, value)


class OnlyMemoryHistoricalQueryKind(StrEnum):
    SEMANTIC_EXACT = "SEMANTIC_EXACT"
    EVALUATION_EXACT = "EVALUATION_EXACT"
    PARAMETER_OBSERVATION_EXACT = "PARAMETER_OBSERVATION_EXACT"
    FAILURE_EVIDENCE_EXACT = "FAILURE_EVIDENCE_EXACT"


class OnlyMemoryHistoricalProofStatus(StrEnum):
    MATCH = "MATCH"
    CERTIFIED_NO_MATCH = "CERTIFIED_NO_MATCH"
    PROOF_INCOMPLETE = "PROOF_INCOMPLETE"
    PROOF_UNAVAILABLE = "PROOF_UNAVAILABLE"


class OnlyMemoryFailureOwnerKind(StrEnum):
    RESEARCH_RUN = "RESEARCH_RUN"
    SEARCH_OCCURRENCE = "SEARCH_OCCURRENCE"
    AGENT_OCCURRENCE = "AGENT_OCCURRENCE"
    QUALIFICATION_DECISION = "QUALIFICATION_DECISION"


@dataclass(frozen=True, slots=True)
class OnlyExactSemanticHistorySelectorV1:
    graph_fingerprint: str
    candidate_node_fingerprint: str
    output_name: str
    query_kind: ClassVar[OnlyMemoryHistoricalQueryKind] = OnlyMemoryHistoricalQueryKind.SEMANTIC_EXACT

    def __post_init__(self) -> None:
        _sha(self.graph_fingerprint, "graph_fingerprint")
        _sha(self.candidate_node_fingerprint, "candidate_node_fingerprint")
        if not self.output_name:
            raise ValueError("output_name is required")

    def to_dict(self) -> dict[str, object]:
        return {
            "graph_fingerprint": self.graph_fingerprint,
            "candidate_node_fingerprint": self.candidate_node_fingerprint,
            "output_name": self.output_name,
        }


@dataclass(frozen=True, slots=True)
class OnlyExactStatisticsReferenceV1:
    statistics_fingerprint: str
    statistics_result_fingerprint: str

    def __post_init__(self) -> None:
        _sha(self.statistics_fingerprint, "statistics_fingerprint")
        _sha(self.statistics_result_fingerprint, "statistics_result_fingerprint")

    def to_dict(self) -> dict[str, str]:
        return {
            "statistics_fingerprint": self.statistics_fingerprint,
            "statistics_result_fingerprint": self.statistics_result_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class OnlyExactEvaluationHistorySelectorV1:
    semantic: OnlyExactSemanticHistorySelectorV1
    candidate_fingerprint: str
    dataset_snapshot_fingerprint: str
    specification_fingerprint: str
    result_plan_fingerprint: str
    catalog_generation_fingerprint: str
    runtime_generation_fingerprint: str
    authoring_generation_fingerprint: str | None
    statistics_references: tuple[OnlyExactStatisticsReferenceV1, ...]
    search_experiment_fingerprint: str | None = None
    query_kind: ClassVar[OnlyMemoryHistoricalQueryKind] = OnlyMemoryHistoricalQueryKind.EVALUATION_EXACT

    def __post_init__(self) -> None:
        if not isinstance(self.semantic, OnlyExactSemanticHistorySelectorV1):
            raise ValueError("semantic selector is required")
        for name in (
            "candidate_fingerprint",
            "dataset_snapshot_fingerprint",
            "specification_fingerprint",
            "result_plan_fingerprint",
            "catalog_generation_fingerprint",
            "runtime_generation_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if self.authoring_generation_fingerprint is not None:
            _sha(self.authoring_generation_fingerprint, "authoring_generation_fingerprint")
        if self.search_experiment_fingerprint is not None:
            _sha(self.search_experiment_fingerprint, "search_experiment_fingerprint")
        if not self.statistics_references or self.statistics_references != tuple(
            sorted(
                set(self.statistics_references),
                key=lambda item: (item.statistics_fingerprint, item.statistics_result_fingerprint),
            )
        ):
            raise ValueError("statistics_references must be non-empty, canonical, and unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "semantic": self.semantic.to_dict(),
            "candidate_fingerprint": self.candidate_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "specification_fingerprint": self.specification_fingerprint,
            "result_plan_fingerprint": self.result_plan_fingerprint,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "authoring_generation_fingerprint": self.authoring_generation_fingerprint,
            "statistics_references": [reference.to_dict() for reference in self.statistics_references],
            "search_experiment_fingerprint": self.search_experiment_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class OnlyExactParameterObservationSelectorV1:
    experiment_fingerprint: str
    search_space_fingerprint: str
    proposal_fingerprint: str
    normalized_assignment_fingerprint: str
    grid_ordinal: int
    query_kind: ClassVar[OnlyMemoryHistoricalQueryKind] = OnlyMemoryHistoricalQueryKind.PARAMETER_OBSERVATION_EXACT

    def __post_init__(self) -> None:
        for name in (
            "experiment_fingerprint",
            "search_space_fingerprint",
            "proposal_fingerprint",
            "normalized_assignment_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if type(self.grid_ordinal) is not int or self.grid_ordinal < 0:
            raise ValueError("grid_ordinal must be a non-negative integer")

    @classmethod
    def from_normalized_assignment(
        cls,
        *,
        experiment_fingerprint: str,
        search_space_fingerprint: str,
        proposal_fingerprint: str,
        normalized_assignment: object,
        grid_ordinal: int,
    ) -> OnlyExactParameterObservationSelectorV1:
        return cls(
            experiment_fingerprint,
            search_space_fingerprint,
            proposal_fingerprint,
            only_canonical_fingerprint(normalized_assignment),
            grid_ordinal,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_fingerprint": self.experiment_fingerprint,
            "search_space_fingerprint": self.search_space_fingerprint,
            "proposal_fingerprint": self.proposal_fingerprint,
            "normalized_assignment_fingerprint": self.normalized_assignment_fingerprint,
            "grid_ordinal": self.grid_ordinal,
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchRunTerminalOwnerV1:
    run_id: str
    run_revision: int
    specification_fingerprint: str | None = None
    catalog_generation_fingerprint: str | None = None
    runtime_generation_fingerprint: str | None = None
    search_experiment_fingerprint: str | None = None
    search_iteration_plan_fingerprint: str | None = None
    terminal_state: str = "FAILED"
    owner_kind: ClassVar[OnlyMemoryFailureOwnerKind] = OnlyMemoryFailureOwnerKind.RESEARCH_RUN

    def __post_init__(self) -> None:
        _uuid4(self.run_id, "run_id")
        if type(self.run_revision) is not int or self.run_revision < 0:
            raise ValueError("run_revision must be a non-negative integer")
        if self.terminal_state not in {"FAILED", "CANCELLED"}:
            raise ValueError("terminal_state must be FAILED or CANCELLED")
        for name in (
            "specification_fingerprint",
            "catalog_generation_fingerprint",
            "runtime_generation_fingerprint",
            "search_experiment_fingerprint",
            "search_iteration_plan_fingerprint",
        ):
            value = getattr(self, name)
            if value is not None:
                _sha(value, name)

    def to_dict(self) -> dict[str, object]:
        return {
            "owner_kind": self.owner_kind,
            "run_id": self.run_id,
            "run_revision": self.run_revision,
            "specification_fingerprint": self.specification_fingerprint,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "search_experiment_fingerprint": self.search_experiment_fingerprint,
            "search_iteration_plan_fingerprint": self.search_iteration_plan_fingerprint,
            "terminal_state": self.terminal_state,
        }


@dataclass(frozen=True, slots=True)
class OnlySearchFailureOwnerV1:
    iteration_result_fingerprint: str
    owner_kind: ClassVar[OnlyMemoryFailureOwnerKind] = OnlyMemoryFailureOwnerKind.SEARCH_OCCURRENCE

    def __post_init__(self) -> None:
        _sha(self.iteration_result_fingerprint, "iteration_result_fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {"owner_kind": self.owner_kind, "iteration_result_fingerprint": self.iteration_result_fingerprint}


@dataclass(frozen=True, slots=True)
class OnlyAgentFailureOwnerV1:
    occurrence_fingerprint: str
    owner_kind: ClassVar[OnlyMemoryFailureOwnerKind] = OnlyMemoryFailureOwnerKind.AGENT_OCCURRENCE

    def __post_init__(self) -> None:
        _sha(self.occurrence_fingerprint, "occurrence_fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {"owner_kind": self.owner_kind, "occurrence_fingerprint": self.occurrence_fingerprint}


@dataclass(frozen=True, slots=True)
class OnlyQualificationFailureOwnerV1:
    decision_fingerprint: str
    owner_kind: ClassVar[OnlyMemoryFailureOwnerKind] = OnlyMemoryFailureOwnerKind.QUALIFICATION_DECISION

    def __post_init__(self) -> None:
        _sha(self.decision_fingerprint, "decision_fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {"owner_kind": self.owner_kind, "decision_fingerprint": self.decision_fingerprint}


OnlyExactFailureOwnerV1 = (
    OnlyResearchRunTerminalOwnerV1
    | OnlySearchFailureOwnerV1
    | OnlyAgentFailureOwnerV1
    | OnlyQualificationFailureOwnerV1
)


@dataclass(frozen=True, slots=True)
class OnlyExactFailureEvidenceSelectorV1:
    classification: str
    stable_code: str | None
    owner: OnlyExactFailureOwnerV1
    failure_phase: str | None = None
    query_kind: ClassVar[OnlyMemoryHistoricalQueryKind] = OnlyMemoryHistoricalQueryKind.FAILURE_EVIDENCE_EXACT

    def __post_init__(self) -> None:
        if not self.classification:
            raise ValueError("classification is required")
        if not isinstance(
            self.owner,
            (
                OnlyResearchRunTerminalOwnerV1,
                OnlySearchFailureOwnerV1,
                OnlyAgentFailureOwnerV1,
                OnlyQualificationFailureOwnerV1,
            ),
        ):
            raise ValueError("typed failure owner is required")
        if self.failure_phase is not None and not self.failure_phase:
            raise ValueError("failure_phase must be non-empty when provided")
        if self.failure_phase is not None and not isinstance(self.owner, OnlyResearchRunTerminalOwnerV1):
            raise ValueError("failure_phase is only valid for a Research Run owner")
        run_cancelled = (
            isinstance(self.owner, OnlyResearchRunTerminalOwnerV1) and self.owner.terminal_state == "CANCELLED"
        )
        if run_cancelled and (self.stable_code is not None or self.failure_phase is not None):
            raise ValueError("CANCELLED does not accept structured failure selectors")
        if not run_cancelled and (not isinstance(self.stable_code, str) or not self.stable_code):
            raise ValueError("stable_code is required outside CANCELLED")
        allowed = (
            self.classification == "OPERATIONAL_FAILURE"
            if isinstance(self.owner, (OnlyResearchRunTerminalOwnerV1, OnlyAgentFailureOwnerV1))
            else self.classification in {"OPERATIONAL_FAILURE", "SEARCH_OR_BUDGET_STOP"}
            if isinstance(self.owner, OnlySearchFailureOwnerV1)
            else self.classification == "QUALIFICATION_REJECT" and self.stable_code == "QUALIFICATION_REJECTED"
        )
        if not allowed:
            raise ValueError("classification is incompatible with the typed failure owner")

    def to_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "stable_code": self.stable_code,
            "owner": self.owner.to_dict(),
            "failure_phase": self.failure_phase,
        }


OnlyMemoryHistoricalSelectorV1 = (
    OnlyExactSemanticHistorySelectorV1
    | OnlyExactEvaluationHistorySelectorV1
    | OnlyExactParameterObservationSelectorV1
    | OnlyExactFailureEvidenceSelectorV1
)


@dataclass(frozen=True, slots=True)
class OnlyMemoryHistoricalQueryV1:
    projection_revision_fingerprint: str
    exact_selector: OnlyMemoryHistoricalSelectorV1
    query_schema_version: int = QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _sha(self.projection_revision_fingerprint, "projection_revision_fingerprint")
        if not isinstance(
            self.exact_selector,
            (
                OnlyExactSemanticHistorySelectorV1,
                OnlyExactEvaluationHistorySelectorV1,
                OnlyExactParameterObservationSelectorV1,
                OnlyExactFailureEvidenceSelectorV1,
            ),
        ):
            raise ValueError("exact_selector is unsupported")
        if type(self.query_schema_version) is not int or self.query_schema_version < 1:
            raise ValueError("query_schema_version must be a positive integer")

    @property
    def query_kind(self) -> OnlyMemoryHistoricalQueryKind:
        return self.exact_selector.query_kind

    @property
    def query_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "query_schema_version": self.query_schema_version,
            "projection_revision_fingerprint": self.projection_revision_fingerprint,
            "query_kind": self.query_kind,
            "exact_selector": self.exact_selector.to_dict(),
        }
        if include_fingerprint:
            payload["query_fingerprint"] = self.query_fingerprint
        return payload


@dataclass(frozen=True, slots=True, init=False)
class OnlyMemoryHistoricalMatchV1:
    record_kind: str
    _facets_json: str
    source_refs: tuple[OnlyMemorySourceRefV1, ...]

    def __init__(self, record: OnlyMemoryProjectionRecordV1) -> None:
        object.__setattr__(self, "record_kind", record.kind)
        object.__setattr__(self, "_facets_json", only_canonical_json(dict(record.facets)))
        object.__setattr__(self, "source_refs", record.source_refs)

    def to_dict(self) -> dict[str, object]:
        import json

        return {
            "record_kind": self.record_kind,
            "facets": json.loads(self._facets_json),
            "source_refs": [ref.to_dict() for ref in self.source_refs],
        }


@dataclass(frozen=True, slots=True)
class OnlyMemoryHistoricalProofV1:
    query_fingerprint: str
    projection_revision_fingerprint: str
    projection_logical_digest: str | None
    source_manifest_fingerprint: str | None
    proof_status: OnlyMemoryHistoricalProofStatus
    ordered_matches: tuple[OnlyMemoryHistoricalMatchV1, ...]
    failure_code: str | None = None

    @property
    def result_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "query_fingerprint": self.query_fingerprint,
            "projection_revision_fingerprint": self.projection_revision_fingerprint,
            "projection_logical_digest": self.projection_logical_digest,
            "source_manifest_fingerprint": self.source_manifest_fingerprint,
            "proof_status": self.proof_status,
            "ordered_matches": [match.to_dict() for match in self.ordered_matches],
            "failure_code": self.failure_code,
        }
        if include_fingerprint:
            payload["result_fingerprint"] = self.result_fingerprint
        return payload


class _PredicateVerdict(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    INCOMPLETE = "INCOMPLETE"


def _semantic(record: OnlyMemoryProjectionRecordV1, selector: OnlyExactSemanticHistorySelectorV1) -> _PredicateVerdict:
    if record.kind != "EvaluationProjectionRecord":
        return _PredicateVerdict.NOT_APPLICABLE
    facets = record.facets
    if not _is_sha(facets.get("graph_fingerprint")) or not _is_sha(facets.get("candidate_node_fingerprint")):
        return _PredicateVerdict.INCOMPLETE
    if not isinstance(facets.get("output_name"), str) or not facets["output_name"]:
        return _PredicateVerdict.INCOMPLETE
    return (
        _PredicateVerdict.MATCH
        if all(facets[name] == value for name, value in selector.to_dict().items())
        else _PredicateVerdict.NO_MATCH
    )


def _source_ref_complete(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"source_family", "cut_fingerprint", "locator", "identity", "content_fingerprint"}
        and isinstance(value.get("source_family"), str)
        and bool(value["source_family"])
        and isinstance(value.get("locator"), str)
        and bool(value["locator"])
        and all(_is_sha(value.get(name)) for name in ("cut_fingerprint", "identity", "content_fingerprint"))
    )


def _product_relation_ref_complete(value: object, family: str, command_id: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value)
        == {"source_family", "cut_fingerprint", "locator", "identity", "content_fingerprint", "native_locator"}
        and value.get("source_family") == family
        and value.get("native_locator") == command_id
        and _source_ref_complete({name: item for name, item in value.items() if name != "native_locator"})
    )


def _exact_source_ref(record: OnlyMemoryProjectionRecordV1, family: str, locator: object, identity: object) -> bool:
    refs = tuple(ref for ref in record.source_refs if ref.source_family == family)
    matches = tuple(ref for ref in refs if ref.locator == locator and ref.identity == identity)
    return (
        isinstance(locator, str)
        and isinstance(identity, str)
        and len(matches) == 1
        and all(_source_ref_complete(ref.to_dict()) for ref in refs)
    )


def _nested_ref_matches_record_source(record: OnlyMemoryProjectionRecordV1, value: Mapping[str, object]) -> bool:
    source_part = {name: item for name, item in value.items() if name != "native_locator"}
    return sum(ref.to_dict() == source_part for ref in record.source_refs) == 1


def _search_lineage_complete(record: OnlyMemoryProjectionRecordV1, value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    required = {
        "search_method",
        "experiment_fingerprint",
        "iteration_plan_fingerprint",
        "iteration_result_fingerprint",
        "research_product_command_id",
        "research_product_command_kind",
        "research_product_command_fingerprint",
        "experiment_source_ref",
        "plan_source_ref",
        "admission_source_ref",
        "receipt_source_ref",
        "iteration_result_source_ref",
    }
    result = value.get("iteration_result_fingerprint")
    result_ref = value.get("iteration_result_source_ref")
    command_id = value.get("research_product_command_id")
    experiment = value.get("experiment_fingerprint")
    plan = value.get("iteration_plan_fingerprint")
    experiment_ref = value.get("experiment_source_ref")
    plan_ref = value.get("plan_source_ref")
    return (
        set(value) == required
        and value.get("search_method") in {"SYMBOLIC", "PARAMETER"}
        and _is_sha(value.get("experiment_fingerprint"))
        and _is_sha(value.get("iteration_plan_fingerprint"))
        and (result is None or _is_sha(result))
        and _is_uuid4(command_id)
        and value.get("research_product_command_kind") == "CREATE_RESEARCH_RUN"
        and _is_sha(value.get("research_product_command_fingerprint"))
        and isinstance(experiment_ref, Mapping)
        and _source_ref_complete(experiment_ref)
        and experiment_ref.get("source_family") == "SEARCH_PROVENANCE"
        and experiment_ref.get("locator") == f"experiments/{experiment}"
        and experiment_ref.get("identity") == experiment
        and _nested_ref_matches_record_source(record, experiment_ref)
        and isinstance(plan_ref, Mapping)
        and _source_ref_complete(plan_ref)
        and plan_ref.get("source_family") == "SEARCH_PROVENANCE"
        and plan_ref.get("locator") == f"iteration-plans/{plan}"
        and plan_ref.get("identity") == plan
        and _nested_ref_matches_record_source(record, plan_ref)
        and _product_relation_ref_complete(value.get("admission_source_ref"), "PRODUCT_COMMAND_ADMISSION", command_id)
        and _nested_ref_matches_record_source(record, cast(Mapping[str, object], value["admission_source_ref"]))
        and _product_relation_ref_complete(value.get("receipt_source_ref"), "PRODUCT_COMMAND_RECEIPT", command_id)
        and _nested_ref_matches_record_source(record, cast(Mapping[str, object], value["receipt_source_ref"]))
        and (
            (result is None and result_ref is None)
            or (
                result is not None
                and isinstance(result_ref, Mapping)
                and _source_ref_complete(result_ref)
                and result_ref.get("source_family") == "SEARCH_PROVENANCE"
                and result_ref.get("locator") == f"iteration-results/{result}"
                and result_ref.get("identity") == result
                and _nested_ref_matches_record_source(record, result_ref)
            )
        )
    )


def _statistics_references(value: object) -> tuple[OnlyExactStatisticsReferenceV1, ...] | None:
    if not isinstance(value, list):
        return None
    try:
        references = tuple(
            OnlyExactStatisticsReferenceV1(
                cast(str, item["statistics_fingerprint"]), cast(str, item["statistics_result_fingerprint"])
            )
            for item in value
            if isinstance(item, Mapping) and set(item) == {"statistics_fingerprint", "statistics_result_fingerprint"}
        )
    except (KeyError, ValueError):
        return None
    canonical = tuple(
        sorted(references, key=lambda item: (item.statistics_fingerprint, item.statistics_result_fingerprint))
    )
    if (
        len(references) != len(value)
        or not references
        or references != canonical
        or len(set(references)) != len(references)
    ):
        return None
    return references


_RUN_STATES = frozenset(state.value for state in OnlyResearchRunState)
_RUN_FAILURE_PHASES = frozenset(phase.value for phase in OnlyResearchRunFailurePhase)


def _run_evaluation_closure_complete(
    record: OnlyMemoryProjectionRecordV1,
    closure: Mapping[str, object],
    *,
    enclosing_result_fingerprint: str,
) -> bool:
    expected = {
        "run_id",
        "run_revision",
        "run_state",
        "specification_fingerprint",
        "research_result_fingerprint",
        "artifact_content_fingerprint",
        "catalog_generation_fingerprint",
        "runtime_generation_fingerprint",
        "authoring_generation_fingerprint",
        "calculation_execution_evidence_fingerprints",
        "run_source_ref",
        "search_lineage",
    }
    authoring = closure.get("authoring_generation_fingerprint")
    evidence = closure.get("calculation_execution_evidence_fingerprints")
    lineage = closure.get("search_lineage")
    result = closure.get("research_result_fingerprint")
    artifact = closure.get("artifact_content_fingerprint")
    state = closure.get("run_state")
    common = (
        set(closure) == expected
        and _is_uuid4(closure.get("run_id"))
        and type(closure.get("run_revision")) is int
        and cast(int, closure["run_revision"]) >= 0
        and isinstance(state, str)
        and state in _RUN_STATES
        and all(
            _is_sha(closure.get(name))
            for name in (
                "specification_fingerprint",
                "catalog_generation_fingerprint",
                "runtime_generation_fingerprint",
            )
        )
        and result == enclosing_result_fingerprint
        and (artifact is None or _is_sha(artifact))
        and (authoring is None or _is_sha(authoring))
        and isinstance(evidence, list)
        and all(_is_sha(item) for item in evidence)
        and evidence == sorted(set(evidence))
        and _source_ref_complete(closure.get("run_source_ref"))
        and (lineage is None or _search_lineage_complete(record, lineage))
        and (artifact is None or result is not None)
        and (not evidence or result is not None)
    )
    if not common:
        return False
    if state == "COMPLETED":
        return _is_sha(result) and _is_sha(artifact) and bool(evidence)
    if state == "QUEUED":
        return False
    return state not in {"RUNNING", "CANCEL_REQUESTED"} or not evidence


def _evaluation(
    record: OnlyMemoryProjectionRecordV1, selector: OnlyExactEvaluationHistorySelectorV1
) -> _PredicateVerdict:
    # Selector-bound matrix: semantic output, Candidate, Dataset, Specification, Plan, Statistics
    # logical/result pairs, Catalog, Runtime, nullable Authoring, and optional Search Experiment.
    # Result, completed Run, Artifact, and execution Evidence are exact returned occurrence proof.
    semantic = _semantic(record, selector.semantic)
    if semantic is _PredicateVerdict.NOT_APPLICABLE:
        return semantic
    if semantic is _PredicateVerdict.INCOMPLETE:
        return _PredicateVerdict.INCOMPLETE
    facets = record.facets
    if not all(
        _is_sha(facets.get(name))
        for name in (
            "candidate_fingerprint",
            "dataset_snapshot_fingerprint",
            "research_result_locator",
            "research_result_fingerprint",
        )
    ) or not isinstance(facets.get("run_evaluation_closures"), list):
        return _PredicateVerdict.INCOMPLETE
    statistics = _statistics_references(facets.get("statistics_references"))
    if statistics is None or not _exact_source_ref(
        record, "RESEARCH_RESULT", facets["research_result_locator"], facets["research_result_fingerprint"]
    ):
        return _PredicateVerdict.INCOMPLETE
    closures = cast(list[object], facets["run_evaluation_closures"])
    result_fingerprint = cast(str, facets["research_result_fingerprint"])
    if any(
        not isinstance(closure, Mapping)
        or not _run_evaluation_closure_complete(record, closure, enclosing_result_fingerprint=result_fingerprint)
        for closure in closures
    ):
        return _PredicateVerdict.INCOMPLETE
    if (
        semantic is _PredicateVerdict.NO_MATCH
        or facets["candidate_fingerprint"] != selector.candidate_fingerprint
        or facets["dataset_snapshot_fingerprint"] != selector.dataset_snapshot_fingerprint
        or facets["research_result_locator"] != selector.result_plan_fingerprint
        or statistics != selector.statistics_references
    ):
        return _PredicateVerdict.NO_MATCH
    for closure in closures:
        assert isinstance(closure, Mapping)
        if closure["run_state"] != "COMPLETED":
            continue
        lineage = closure.get("search_lineage")
        if selector.search_experiment_fingerprint is not None and (
            not isinstance(lineage, Mapping)
            or lineage.get("experiment_fingerprint") != selector.search_experiment_fingerprint
        ):
            continue
        if (
            closure["specification_fingerprint"] == selector.specification_fingerprint
            and closure["research_result_fingerprint"] == result_fingerprint
            and closure["catalog_generation_fingerprint"] == selector.catalog_generation_fingerprint
            and closure["runtime_generation_fingerprint"] == selector.runtime_generation_fingerprint
            and closure.get("authoring_generation_fingerprint") == selector.authoring_generation_fingerprint
        ):
            return _PredicateVerdict.MATCH
    return _PredicateVerdict.NO_MATCH


def _parameter(
    record: OnlyMemoryProjectionRecordV1, selector: OnlyExactParameterObservationSelectorV1
) -> _PredicateVerdict:
    if record.kind != "ParameterObservationProjectionRecord":
        return _PredicateVerdict.NOT_APPLICABLE
    facets = record.facets
    method = facets.get("search_method")
    if not isinstance(method, str) or method not in {"SYMBOLIC", "PARAMETER"}:
        return _PredicateVerdict.INCOMPLETE
    if method == "SYMBOLIC":
        return (
            _PredicateVerdict.INCOMPLETE
            if {"search_space_fingerprint", "normalized_assignment", "grid_ordinal"} & set(facets)
            else _PredicateVerdict.NOT_APPLICABLE
        )
    if not all(
        _is_sha(facets.get(name))
        for name in (
            "experiment_fingerprint",
            "search_space_fingerprint",
            "proposal_fingerprint",
            "iteration_plan_fingerprint",
        )
    ):
        return _PredicateVerdict.INCOMPLETE
    assignment = facets.get("normalized_assignment")
    ordinal = facets.get("grid_ordinal")
    if (
        not isinstance(assignment, list)
        or type(ordinal) is not int
        or ordinal < 0
        or not _exact_source_ref(
            record,
            "SEARCH_PROVENANCE",
            f"iteration-plans/{facets['iteration_plan_fingerprint']}",
            facets["iteration_plan_fingerprint"],
        )
        or not any(
            _source_ref_complete(ref.to_dict())
            and ref.locator == f"experiments/{facets['experiment_fingerprint']}"
            and ref.identity == facets["experiment_fingerprint"]
            for ref in record.source_refs
            if ref.source_family == "SEARCH_PROVENANCE"
        )
    ):
        return _PredicateVerdict.INCOMPLETE
    return (
        _PredicateVerdict.MATCH
        if (
            facets["experiment_fingerprint"] == selector.experiment_fingerprint
            and facets["search_space_fingerprint"] == selector.search_space_fingerprint
            and facets["proposal_fingerprint"] == selector.proposal_fingerprint
            and only_canonical_fingerprint(assignment) == selector.normalized_assignment_fingerprint
            and ordinal == selector.grid_ordinal
        )
        else _PredicateVerdict.NO_MATCH
    )


def _owner_refs(record: OnlyMemoryProjectionRecordV1, family: str) -> tuple[OnlyMemorySourceRefV1, ...]:
    return tuple(ref for ref in record.source_refs if ref.source_family == family)


def _owner_ref(record: OnlyMemoryProjectionRecordV1, family: str) -> OnlyMemorySourceRefV1 | None:
    refs = _owner_refs(record, family)
    if len(refs) != 1 or not all(
        (
            ref.source_family
            and ref.locator
            and _is_sha(ref.cut_fingerprint)
            and _is_sha(ref.identity)
            and _is_sha(ref.content_fingerprint)
        )
        for ref in refs
    ):
        return None
    return refs[0]


def _run_owner_complete(record: OnlyMemoryProjectionRecordV1, context: object) -> bool:
    if not isinstance(context, Mapping) or set(record.facets) != {
        "owner_kind",
        "classification",
        "run_context",
        "failure_phase",
        "failure_code",
        "failure_detail",
    }:
        return False
    context = record.facets.get("run_context")
    assert isinstance(context, Mapping)
    expected = {
        "run_id",
        "run_revision",
        "run_state",
        "specification_fingerprint",
        "research_result_fingerprint",
        "artifact_content_fingerprint",
        "catalog_generation_fingerprint",
        "runtime_generation_fingerprint",
        "authoring_generation_fingerprint",
        "calculation_execution_evidence_fingerprints",
        "run_source_ref",
        "search_lineage",
    }
    evidence = context.get("calculation_execution_evidence_fingerprints")
    lineage = context.get("search_lineage")
    source = _owner_ref(record, "RESEARCH_RUN")
    result = context.get("research_result_fingerprint")
    artifact = context.get("artifact_content_fingerprint")
    authoring = context.get("authoring_generation_fingerprint")
    common = (
        record.facets.get("owner_kind") == OnlyMemoryFailureOwnerKind.RESEARCH_RUN
        and record.facets.get("classification") == "OPERATIONAL_FAILURE"
        and set(context) == expected
        and _is_uuid4(context.get("run_id"))
        and type(context.get("run_revision")) is int
        and cast(int, context["run_revision"]) >= 0
        and context.get("run_state") in {"FAILED", "CANCELLED"}
        and all(
            _is_sha(context.get(name))
            for name in (
                "specification_fingerprint",
                "catalog_generation_fingerprint",
                "runtime_generation_fingerprint",
            )
        )
        and (result is None or _is_sha(result))
        and (artifact is None or _is_sha(artifact))
        and (authoring is None or _is_sha(authoring))
        and isinstance(evidence, list)
        and all(_is_sha(value) for value in evidence)
        and evidence == sorted(set(evidence))
        and (lineage is None or _search_lineage_complete(record, lineage))
        and source is not None
        and _source_ref_complete(context.get("run_source_ref"))
        and source.to_dict() == context.get("run_source_ref")
        and (artifact is None or result is not None)
        and (not evidence or result is not None)
    )
    if not common:
        return False
    if context["run_state"] == "FAILED":
        return (
            isinstance(record.facets.get("failure_code"), str)
            and bool(record.facets["failure_code"])
            and record.facets.get("failure_phase") in _RUN_FAILURE_PHASES
            and isinstance(record.facets.get("failure_detail"), str)
            and bool(record.facets["failure_detail"])
        )
    return all(record.facets.get(name) is None for name in ("failure_code", "failure_phase", "failure_detail"))


def _run_owner_equal(context: Mapping[str, object], selector: OnlyResearchRunTerminalOwnerV1) -> bool:
    lineage = context.get("search_lineage")
    constraints = {
        "run_id": selector.run_id,
        "run_revision": selector.run_revision,
        "run_state": selector.terminal_state,
        "specification_fingerprint": selector.specification_fingerprint,
        "catalog_generation_fingerprint": selector.catalog_generation_fingerprint,
        "runtime_generation_fingerprint": selector.runtime_generation_fingerprint,
    }
    if any(value is not None and context.get(name) != value for name, value in constraints.items()):
        return False
    if selector.search_experiment_fingerprint is not None and (
        not isinstance(lineage, Mapping)
        or lineage.get("experiment_fingerprint") != selector.search_experiment_fingerprint
    ):
        return False
    return selector.search_iteration_plan_fingerprint is None or (
        isinstance(lineage, Mapping)
        and lineage.get("iteration_plan_fingerprint") == selector.search_iteration_plan_fingerprint
    )


def _search_owner_complete(record: OnlyMemoryProjectionRecordV1) -> bool:
    if set(record.facets) != {"owner_kind", "classification", "failure_code", "iteration_result_fingerprint"}:
        return False
    identity = record.facets.get("iteration_result_fingerprint")
    source = _owner_ref(record, "SEARCH_PROVENANCE")
    return (
        record.facets.get("owner_kind") == OnlyMemoryFailureOwnerKind.SEARCH_OCCURRENCE
        and record.facets.get("classification") in {"OPERATIONAL_FAILURE", "SEARCH_OR_BUDGET_STOP"}
        and _is_sha(identity)
        and source is not None
        and source.identity == identity
        and source.locator == f"iteration-results/{identity}"
        and isinstance(record.facets.get("failure_code"), str)
        and bool(record.facets["failure_code"])
    )


def _agent_owner_complete(record: OnlyMemoryProjectionRecordV1) -> bool:
    if set(record.facets) != {"owner_kind", "classification", "failure_code", "outcome"}:
        return False
    source = _owner_ref(record, "AGENT_PROVENANCE")
    if (
        record.facets.get("owner_kind") != OnlyMemoryFailureOwnerKind.AGENT_OCCURRENCE
        or record.facets.get("classification") != "OPERATIONAL_FAILURE"
        or source is None
        or not isinstance(record.facets.get("failure_code"), str)
        or not record.facets["failure_code"]
    ):
        return False
    outcome = record.facets.get("outcome")
    code = record.facets["failure_code"]
    if not isinstance(outcome, str):
        return False
    if source.locator == f"model-calls/results/{source.identity}":
        return code == {
            "FAILED": "AGENT_MODEL_CALL_FAILED",
            "OUTCOME_UNKNOWN": "AGENT_MODEL_CALL_OUTCOME_UNKNOWN",
            "RESPONSE_INVALID": "AGENT_MODEL_RESPONSE_INVALID",
        }.get(outcome)
    if source.locator == f"tool-calls/results/{source.identity}":
        return code == {"FAILED": "AGENT_TOOL_CALL_FAILED", "RESULT_INVALID": "AGENT_TOOL_RESULT_INVALID"}.get(outcome)
    return False


def _qualification_owner_complete(record: OnlyMemoryProjectionRecordV1) -> bool:
    if set(record.facets) != {
        "owner_kind",
        "classification",
        "subject_strategy_fingerprint",
        "policy_id",
        "policy_version",
        "policy_fingerprint",
        "evidence_refs",
    }:
        return False
    return (
        record.facets.get("owner_kind") == OnlyMemoryFailureOwnerKind.QUALIFICATION_DECISION
        and record.facets.get("classification") == "QUALIFICATION_REJECT"
    )


def _qualification_owner_context_complete(record: OnlyMemoryProjectionRecordV1) -> bool:
    facets = record.facets
    source = _owner_ref(record, "QUALIFICATION_DECISION")
    evidence = facets.get("evidence_refs")
    evidence_keys = [only_canonical_json(item) for item in evidence] if isinstance(evidence, list) else []
    return _qualification_owner_complete(record) and (
        _is_sha(facets.get("subject_strategy_fingerprint"))
        and isinstance(facets.get("policy_id"), str)
        and bool(facets["policy_id"])
        and isinstance(facets.get("policy_version"), str)
        and bool(facets["policy_version"])
        and _is_sha(facets.get("policy_fingerprint"))
        and isinstance(evidence, list)
        and bool(evidence)
        and evidence_keys == sorted(set(evidence_keys))
        and all(
            isinstance(item, Mapping)
            and set(item) == {"kind", "evidence_fingerprint", "locator_fingerprint", "subject_binding_fingerprint"}
            and isinstance(item.get("kind"), str)
            and _is_sha(item.get("evidence_fingerprint"))
            and (item.get("locator_fingerprint") is None or _is_sha(item.get("locator_fingerprint")))
            and (item.get("subject_binding_fingerprint") is None or _is_sha(item.get("subject_binding_fingerprint")))
            for item in evidence
        )
        and source is not None
        and source.locator == source.identity
    )


def _owner_kind_proven(record: OnlyMemoryProjectionRecordV1, owner_kind: OnlyMemoryFailureOwnerKind) -> bool:
    facets = record.facets
    if owner_kind is OnlyMemoryFailureOwnerKind.RESEARCH_RUN:
        context = facets.get("run_context")
        source = _owner_ref(record, "RESEARCH_RUN")
        return isinstance(context, Mapping) and source is not None and source.to_dict() == context.get("run_source_ref")
    if owner_kind is OnlyMemoryFailureOwnerKind.SEARCH_OCCURRENCE:
        identity = facets.get("iteration_result_fingerprint")
        source = _owner_ref(record, "SEARCH_PROVENANCE")
        return (
            _is_sha(identity)
            and source is not None
            and source.identity == identity
            and source.locator == f"iteration-results/{identity}"
        )
    if owner_kind is OnlyMemoryFailureOwnerKind.AGENT_OCCURRENCE:
        return any(
            _source_ref_complete(ref.to_dict())
            and ref.locator in {f"model-calls/results/{ref.identity}", f"tool-calls/results/{ref.identity}"}
            for ref in _owner_refs(record, "AGENT_PROVENANCE")
        )
    source = _owner_ref(record, "QUALIFICATION_DECISION")
    return source is not None and source.locator == source.identity


def _failure(record: OnlyMemoryProjectionRecordV1, selector: OnlyExactFailureEvidenceSelectorV1) -> _PredicateVerdict:
    if record.kind != "FailureEvidenceProjectionRecord":
        return _PredicateVerdict.NOT_APPLICABLE
    owner_kind = record.facets.get("owner_kind")
    if not isinstance(owner_kind, str):
        return _PredicateVerdict.INCOMPLETE
    try:
        parsed_owner_kind = OnlyMemoryFailureOwnerKind(owner_kind)
    except ValueError:
        return _PredicateVerdict.INCOMPLETE
    owner = selector.owner
    if not _owner_kind_proven(record, parsed_owner_kind):
        return _PredicateVerdict.INCOMPLETE
    if parsed_owner_kind is not owner.owner_kind:
        return _PredicateVerdict.NOT_APPLICABLE
    if isinstance(owner, OnlyResearchRunTerminalOwnerV1):
        context = record.facets.get("run_context")
        complete = _run_owner_complete(record, context)
        owned = complete and _run_owner_equal(cast(Mapping[str, object], context), owner)
    elif isinstance(owner, OnlySearchFailureOwnerV1):
        complete = _search_owner_complete(record)
        owned = complete and record.facets["iteration_result_fingerprint"] == owner.iteration_result_fingerprint
    elif isinstance(owner, OnlyAgentFailureOwnerV1):
        complete = _agent_owner_complete(record)
        source = _owner_ref(record, "AGENT_PROVENANCE")
        owned = complete and source is not None and source.identity == owner.occurrence_fingerprint
    else:
        complete = _qualification_owner_context_complete(record)
        source = _owner_ref(record, "QUALIFICATION_DECISION")
        owned = complete and source is not None and source.identity == owner.decision_fingerprint
    if not complete:
        return _PredicateVerdict.INCOMPLETE
    if not owned:
        return _PredicateVerdict.NO_MATCH
    classification = cast(str, record.facets["classification"])
    if classification != selector.classification:
        return _PredicateVerdict.NO_MATCH
    if isinstance(owner, OnlyResearchRunTerminalOwnerV1) and owner.terminal_state == "CANCELLED":
        return _PredicateVerdict.MATCH
    code = record.facets.get("failure_code")
    stable_code = "QUALIFICATION_REJECTED" if classification == "QUALIFICATION_REJECT" else code
    phase = record.facets.get("failure_phase")
    assert isinstance(stable_code, str)
    return (
        _PredicateVerdict.MATCH
        if stable_code == selector.stable_code and (selector.failure_phase is None or phase == selector.failure_phase)
        else _PredicateVerdict.NO_MATCH
    )


def only_query_experiment_memory_history(
    revisions: OnlyExperimentMemoryRevisionStore,
    query: OnlyMemoryHistoricalQueryV1,
) -> OnlyMemoryHistoricalProofV1:
    if query.query_schema_version != QUERY_SCHEMA_VERSION:
        return OnlyMemoryHistoricalProofV1(
            query.query_fingerprint,
            query.projection_revision_fingerprint,
            None,
            None,
            OnlyMemoryHistoricalProofStatus.PROOF_UNAVAILABLE,
            (),
            "QUERY_SCHEMA_UNSUPPORTED",
        )
    try:
        projection = revisions.load_verified(query.projection_revision_fingerprint)
    except OnlyMemoryProjectionError as exc:
        return OnlyMemoryHistoricalProofV1(
            query.query_fingerprint,
            query.projection_revision_fingerprint,
            None,
            None,
            OnlyMemoryHistoricalProofStatus.PROOF_UNAVAILABLE,
            (),
            str(exc),
        )

    matched: dict[str, OnlyMemoryHistoricalMatchV1] = {}
    incomplete = False
    for record in projection.records:
        selector = query.exact_selector
        if isinstance(selector, OnlyExactSemanticHistorySelectorV1):
            outcome = _semantic(record, selector)
        elif isinstance(selector, OnlyExactEvaluationHistorySelectorV1):
            outcome = _evaluation(record, selector)
        elif isinstance(selector, OnlyExactParameterObservationSelectorV1):
            outcome = _parameter(record, selector)
        else:
            outcome = _failure(record, selector)
        if outcome is _PredicateVerdict.INCOMPLETE:
            incomplete = True
        elif outcome is _PredicateVerdict.MATCH:
            match = OnlyMemoryHistoricalMatchV1(record)
            matched[only_canonical_json(match.to_dict())] = match
    ordered = tuple(matched[key] for key in sorted(matched))
    status = (
        OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
        if incomplete
        else OnlyMemoryHistoricalProofStatus.MATCH
        if ordered
        else OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )
    return OnlyMemoryHistoricalProofV1(
        query.query_fingerprint,
        projection.revision_fingerprint,
        projection.logical_digest,
        projection.source_manifest.manifest_fingerprint,
        status,
        ordered,
        "PREDICATE_COMPLETENESS_UNPROVEN" if status is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE else None,
    )


__all__ = [name for name in globals() if name.startswith("Only") or name == "only_query_experiment_memory_history"]
