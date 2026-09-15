"""Revision-bound deterministic reads over immutable Experiment Memory projections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, cast

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

from .projector import OnlyMemoryProjectionRecordV1, OnlyMemorySourceRefV1
from .source_manifest import OnlyMemoryProjectionError
from .store import OnlyExperimentMemoryRevisionStore

QUERY_SCHEMA_VERSION = 1


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")
    return value


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
class OnlyExactEvaluationHistorySelectorV1:
    semantic: OnlyExactSemanticHistorySelectorV1
    candidate_fingerprint: str
    dataset_snapshot_fingerprint: str
    specification_fingerprint: str
    result_plan_fingerprint: str
    catalog_generation_fingerprint: str
    runtime_generation_fingerprint: str
    authoring_generation_fingerprint: str | None
    statistics_fingerprints: tuple[str, ...]
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
        if self.statistics_fingerprints != tuple(sorted(set(self.statistics_fingerprints))):
            raise ValueError("statistics_fingerprints must be canonical and unique")
        for fingerprint in self.statistics_fingerprints:
            _sha(fingerprint, "statistics_fingerprint")

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
            "statistics_fingerprints": list(self.statistics_fingerprints),
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
class OnlyExactFailureEvidenceSelectorV1:
    classification: str
    stable_code: str
    owning_identity: str
    query_kind: ClassVar[OnlyMemoryHistoricalQueryKind] = OnlyMemoryHistoricalQueryKind.FAILURE_EVIDENCE_EXACT

    def __post_init__(self) -> None:
        if not self.classification or not self.stable_code:
            raise ValueError("classification and stable_code are required")
        _sha(self.owning_identity, "owning_identity")

    def to_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "stable_code": self.stable_code,
            "owning_identity": self.owning_identity,
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
    required = ("graph_fingerprint", "candidate_node_fingerprint", "output_name")
    if any(not isinstance(facets.get(name), str) for name in required):
        return None
    return all(facets[name] == value for name, value in selector.to_dict().items())


def _evaluation(record: OnlyMemoryProjectionRecordV1, selector: OnlyExactEvaluationHistorySelectorV1) -> bool | None:
    semantic = _semantic(record, selector.semantic)
    if semantic is not True:
        return semantic
    facets = record.facets
    required = {
        "candidate_fingerprint": str,
        "dataset_snapshot_fingerprint": str,
        "research_result_locator": str,
        "research_result_fingerprint": str,
        "statistics_references": list,
        "run_evaluation_closures": list,
    }
    if any(not isinstance(facets.get(name), kind) for name, kind in required.items()):
        return None
    statistics = cast(list[object], facets["statistics_references"])
    if any(
        not isinstance(item, dict) or not isinstance(item.get("statistics_fingerprint"), str) for item in statistics
    ):
        return None
    if (
        facets["candidate_fingerprint"] != selector.candidate_fingerprint
        or facets["dataset_snapshot_fingerprint"] != selector.dataset_snapshot_fingerprint
        or facets["research_result_locator"] != selector.result_plan_fingerprint
        or tuple(sorted(cast(dict[str, str], item)["statistics_fingerprint"] for item in statistics))
        != selector.statistics_fingerprints
    ):
        return False
    result_fingerprint = cast(str, facets["research_result_fingerprint"])
    for closure in cast(list[object], facets["run_evaluation_closures"]):
        if not isinstance(closure, dict):
            return None
        required_closure = {
            "run_id": str,
            "run_revision": int,
            "run_state": str,
            "specification_fingerprint": str,
            "research_result_fingerprint": str,
            "artifact_content_fingerprint": str,
            "catalog_generation_fingerprint": str,
            "runtime_generation_fingerprint": str,
            "calculation_execution_evidence_fingerprints": list,
        }
        if closure.get("run_state") != "COMPLETED":
            continue
        if any(not isinstance(closure.get(name), kind) for name, kind in required_closure.items()):
            return None
        evidence = closure["calculation_execution_evidence_fingerprints"]
        if not evidence or any(not isinstance(value, str) for value in evidence):
            continue
        lineage = closure.get("search_lineage")
        if selector.search_experiment_fingerprint is not None and (
            not isinstance(lineage, dict)
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


def _failure(record: OnlyMemoryProjectionRecordV1, selector: OnlyExactFailureEvidenceSelectorV1) -> bool | None:
    if record.kind != "FailureEvidenceProjectionRecord":
        return False
    if not any(ref.identity == selector.owning_identity for ref in record.source_refs):
        return False
    classification = record.facets.get("classification")
    if not isinstance(classification, str):
        return None
    code = record.facets.get("failure_code")
    stable_code = "QUALIFICATION_REJECTED" if classification == "QUALIFICATION_REJECT" else code
    if not isinstance(stable_code, str):
        return None
    return classification == selector.classification and stable_code == selector.stable_code


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
        OnlyMemoryHistoricalProofStatus.MATCH
        if ordered
        else OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
        if complete
        else OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
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
