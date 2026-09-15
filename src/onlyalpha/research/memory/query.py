"""Revision-bound deterministic reads over immutable Experiment Memory projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, cast
from uuid import UUID

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

from .projector import OnlyMemoryProjectionRecordV1, OnlyMemorySourceRefV1
from .source_manifest import OnlyMemoryProjectionError
from .store import OnlyExperimentMemoryRevisionStore

QUERY_SCHEMA_VERSION = 2


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
class OnlyResearchRunFailureOwnerV1:
    run_id: str
    run_revision: int
    specification_fingerprint: str | None = None
    catalog_generation_fingerprint: str | None = None
    runtime_generation_fingerprint: str | None = None
    search_experiment_fingerprint: str | None = None
    search_iteration_plan_fingerprint: str | None = None
    owner_kind: ClassVar[OnlyMemoryFailureOwnerKind] = OnlyMemoryFailureOwnerKind.RESEARCH_RUN

    def __post_init__(self) -> None:
        _uuid4(self.run_id, "run_id")
        if type(self.run_revision) is not int or self.run_revision < 0:
            raise ValueError("run_revision must be a non-negative integer")
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
    OnlyResearchRunFailureOwnerV1 | OnlySearchFailureOwnerV1 | OnlyAgentFailureOwnerV1 | OnlyQualificationFailureOwnerV1
)


@dataclass(frozen=True, slots=True)
class OnlyExactFailureEvidenceSelectorV1:
    classification: str
    stable_code: str
    owner: OnlyExactFailureOwnerV1
    failure_phase: str | None = None
    query_kind: ClassVar[OnlyMemoryHistoricalQueryKind] = OnlyMemoryHistoricalQueryKind.FAILURE_EVIDENCE_EXACT

    def __post_init__(self) -> None:
        if not self.classification or not self.stable_code:
            raise ValueError("classification and stable_code are required")
        if not isinstance(
            self.owner,
            (
                OnlyResearchRunFailureOwnerV1,
                OnlySearchFailureOwnerV1,
                OnlyAgentFailureOwnerV1,
                OnlyQualificationFailureOwnerV1,
            ),
        ):
            raise ValueError("typed failure owner is required")
        if self.failure_phase is not None and not self.failure_phase:
            raise ValueError("failure_phase must be non-empty when provided")
        if self.failure_phase is not None and not isinstance(self.owner, OnlyResearchRunFailureOwnerV1):
            raise ValueError("failure_phase is only valid for a Research Run owner")
        allowed = (
            self.classification == "OPERATIONAL_FAILURE"
            if isinstance(self.owner, (OnlyResearchRunFailureOwnerV1, OnlyAgentFailureOwnerV1))
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


def _semantic(record: OnlyMemoryProjectionRecordV1, selector: OnlyExactSemanticHistorySelectorV1) -> bool | None:
    if record.kind != "EvaluationProjectionRecord":
        return False
    facets = record.facets
    if not _is_sha(facets.get("graph_fingerprint")) or not _is_sha(facets.get("candidate_node_fingerprint")):
        return None
    if not isinstance(facets.get("output_name"), str) or not facets["output_name"]:
        return None
    return all(facets[name] == value for name, value in selector.to_dict().items())


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


def _search_lineage_complete(value: object) -> bool:
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
    return (
        set(value) == required
        and value.get("search_method") in {"SYMBOLIC", "PARAMETER"}
        and _is_sha(value.get("experiment_fingerprint"))
        and _is_sha(value.get("iteration_plan_fingerprint"))
        and (result is None or _is_sha(result))
        and _is_uuid4(value.get("research_product_command_id"))
        and value.get("research_product_command_kind") == "CREATE_RESEARCH_RUN"
        and _is_sha(value.get("research_product_command_fingerprint"))
        and all(
            _source_ref_complete(value.get(name))
            for name in ("experiment_source_ref", "plan_source_ref", "admission_source_ref", "receipt_source_ref")
        )
        and ((result is None and result_ref is None) or (result is not None and _source_ref_complete(result_ref)))
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


def _completed_evaluation_closure_complete(closure: Mapping[str, object]) -> bool:
    # Proof matrix: Run/Result/Artifact/generations/evidence are mandatory; Authoring and per-Run Search
    # lineage are explicit nullable dimensions. Every malformed mandatory field means INCOMPLETE.
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
    return (
        set(closure) == expected
        and _is_uuid4(closure.get("run_id"))
        and type(closure.get("run_revision")) is int
        and cast(int, closure["run_revision"]) >= 0
        and closure.get("run_state") == "COMPLETED"
        and all(
            _is_sha(closure.get(name))
            for name in (
                "specification_fingerprint",
                "research_result_fingerprint",
                "artifact_content_fingerprint",
                "catalog_generation_fingerprint",
                "runtime_generation_fingerprint",
            )
        )
        and (authoring is None or _is_sha(authoring))
        and isinstance(evidence, list)
        and bool(evidence)
        and all(_is_sha(item) for item in evidence)
        and evidence == sorted(set(evidence))
        and _source_ref_complete(closure.get("run_source_ref"))
        and (lineage is None or _search_lineage_complete(lineage))
    )


def _evaluation(record: OnlyMemoryProjectionRecordV1, selector: OnlyExactEvaluationHistorySelectorV1) -> bool | None:
    # Selector-bound matrix: semantic output, Candidate, Dataset, Specification, Plan, Statistics
    # logical/result pairs, Catalog, Runtime, nullable Authoring, and optional Search Experiment.
    # Result, completed Run, Artifact, and execution Evidence are exact returned occurrence proof.
    semantic = _semantic(record, selector.semantic)
    if semantic is not True:
        return semantic
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
        return None
    statistics = _statistics_references(facets.get("statistics_references"))
    if statistics is None:
        return None
    if (
        facets["candidate_fingerprint"] != selector.candidate_fingerprint
        or facets["dataset_snapshot_fingerprint"] != selector.dataset_snapshot_fingerprint
        or facets["research_result_locator"] != selector.result_plan_fingerprint
        or statistics != selector.statistics_references
    ):
        return False
    result_fingerprint = cast(str, facets["research_result_fingerprint"])
    for closure in cast(list[object], facets["run_evaluation_closures"]):
        if not isinstance(closure, Mapping):
            return None
        state = closure.get("run_state")
        if not isinstance(state, str):
            return None
        if state != "COMPLETED":
            continue
        if not _completed_evaluation_closure_complete(closure):
            return None
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
            return True
    return False


def _parameter(record: OnlyMemoryProjectionRecordV1, selector: OnlyExactParameterObservationSelectorV1) -> bool | None:
    if record.kind != "ParameterObservationProjectionRecord":
        return False
    facets = record.facets
    if "search_space_fingerprint" not in facets:
        return False  # Symbolic Plan occurrence, not an incomplete parameter cell.
    required = {
        "experiment_fingerprint": str,
        "search_space_fingerprint": str,
        "proposal_fingerprint": str,
        "normalized_assignment": list,
        "grid_ordinal": int,
    }
    if any(not isinstance(facets.get(name), kind) for name, kind in required.items()):
        return None
    return (
        facets["experiment_fingerprint"] == selector.experiment_fingerprint
        and facets["search_space_fingerprint"] == selector.search_space_fingerprint
        and facets["proposal_fingerprint"] == selector.proposal_fingerprint
        and only_canonical_fingerprint(facets["normalized_assignment"]) == selector.normalized_assignment_fingerprint
        and facets["grid_ordinal"] == selector.grid_ordinal
    )


def _owner_ref(record: OnlyMemoryProjectionRecordV1, family: str) -> OnlyMemorySourceRefV1 | None:
    refs = [ref for ref in record.source_refs if ref.source_family == family]
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


def _run_failure_owner(record: OnlyMemoryProjectionRecordV1, selector: OnlyResearchRunFailureOwnerV1) -> bool | None:
    # Run failure matrix: native UUID4/revision, terminal failed state, exact Specification/Runtime/Catalog,
    # nullable Result/Artifact/Authoring/Search occurrence, canonical Evidence, and exact Run source ref.
    context = record.facets.get("run_context")
    if not isinstance(context, Mapping):
        return False
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
    if not (
        set(context) == expected
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
        and (lineage is None or _search_lineage_complete(lineage))
        and source is not None
        and _source_ref_complete(context.get("run_source_ref"))
        and source.to_dict() == context.get("run_source_ref")
    ):
        return None
    constraints = {
        "run_id": selector.run_id,
        "run_revision": selector.run_revision,
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


def _search_failure_owner(record: OnlyMemoryProjectionRecordV1, selector: OnlySearchFailureOwnerV1) -> bool | None:
    # Search failures use the exact Iteration Result occurrence; a provenance ref of another kind is not ownership.
    identity = record.facets.get("iteration_result_fingerprint")
    source = _owner_ref(record, "SEARCH_PROVENANCE")
    if identity is None:
        return False
    if (
        not _is_sha(identity)
        or source is None
        or source.identity != identity
        or not source.locator.startswith("iteration-results/")
    ):
        return None
    return identity == selector.iteration_result_fingerprint


def _agent_failure_owner(record: OnlyMemoryProjectionRecordV1, selector: OnlyAgentFailureOwnerV1) -> bool | None:
    # Agent operational failures are owned only by their typed model/tool Result occurrence.
    source = _owner_ref(record, "AGENT_PROVENANCE")
    if source is None:
        return False
    if not source.locator.startswith(("model-calls/results/", "tool-calls/results/")):
        return None
    outcome = record.facets.get("outcome")
    if outcome is not None and not isinstance(outcome, str):
        return None
    return source.identity == selector.occurrence_fingerprint


def _qualification_failure_owner(
    record: OnlyMemoryProjectionRecordV1, selector: OnlyQualificationFailureOwnerV1
) -> bool | None:
    # Qualification rejection remains its own exact Decision subject/policy/evidence occurrence.
    facets = record.facets
    source = _owner_ref(record, "QUALIFICATION_DECISION")
    evidence = facets.get("evidence_refs")
    if not (
        _is_sha(facets.get("subject_strategy_fingerprint"))
        and isinstance(facets.get("policy_id"), str)
        and bool(facets["policy_id"])
        and isinstance(facets.get("policy_version"), str)
        and bool(facets["policy_version"])
        and _is_sha(facets.get("policy_fingerprint"))
        and isinstance(evidence, list)
        and bool(evidence)
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
    ):
        return None
    return source.identity == selector.decision_fingerprint


def _failure(record: OnlyMemoryProjectionRecordV1, selector: OnlyExactFailureEvidenceSelectorV1) -> bool | None:
    if record.kind != "FailureEvidenceProjectionRecord":
        return False
    classification = record.facets.get("classification")
    if not isinstance(classification, str):
        return None
    if classification != selector.classification:
        return False
    code = record.facets.get("failure_code")
    stable_code = "QUALIFICATION_REJECTED" if classification == "QUALIFICATION_REJECT" else code
    if not isinstance(stable_code, str) or not stable_code:
        return None
    owner = selector.owner
    if isinstance(owner, OnlyResearchRunFailureOwnerV1):
        owned = _run_failure_owner(record, owner)
    elif isinstance(owner, OnlySearchFailureOwnerV1):
        owned = _search_failure_owner(record, owner)
    elif isinstance(owner, OnlyAgentFailureOwnerV1):
        owned = _agent_failure_owner(record, owner)
    else:
        owned = _qualification_failure_owner(record, owner)
    if owned is not True:
        return owned
    phase = record.facets.get("failure_phase")
    if isinstance(owner, OnlyResearchRunFailureOwnerV1) and not isinstance(phase, str):
        return None
    return stable_code == selector.stable_code and (selector.failure_phase is None or phase == selector.failure_phase)


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
    complete = True
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
        if outcome is None:
            complete = False
        elif outcome:
            match = OnlyMemoryHistoricalMatchV1(record)
            matched[only_canonical_json(match.to_dict())] = match
    ordered = tuple(matched[key] for key in sorted(matched))
    status = (
        OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
        if not complete
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
