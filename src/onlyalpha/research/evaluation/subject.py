"""Canonical pre-run identity for one exact scientific evaluation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance

from .errors import OnlyResearchEvaluationError

if TYPE_CHECKING:
    from onlyalpha.research.specification.model import OnlyResearchSpecification

_FINGERPRINT_DOMAIN = "ONLYALPHA_EXACT_EVALUATION_INTENT_SUBJECT_V1"


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise OnlyResearchEvaluationError("EVALUATION_SUBJECT_INVALID", f"{name} is not a SHA256 fingerprint")
    return value


@dataclass(frozen=True, slots=True)
class OnlyExactEvaluationIntentSubjectV1:
    graph_fingerprint: str
    candidate_node_fingerprint: str
    output_name: str
    candidate_fingerprint: str
    dataset_snapshot_fingerprint: str
    specification_fingerprint: str
    result_plan_fingerprint: str
    statistics_fingerprints: tuple[str, ...]
    catalog_generation_fingerprint: str
    runtime_generation_fingerprint: str
    authoring_generation_fingerprint: str | None

    def __post_init__(self) -> None:
        for name in (
            "graph_fingerprint",
            "candidate_node_fingerprint",
            "candidate_fingerprint",
            "dataset_snapshot_fingerprint",
            "specification_fingerprint",
            "result_plan_fingerprint",
            "catalog_generation_fingerprint",
            "runtime_generation_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if not isinstance(self.output_name, str) or not self.output_name:
            raise OnlyResearchEvaluationError("EVALUATION_SUBJECT_INVALID", "output_name is required")
        if self.authoring_generation_fingerprint is not None:
            _sha(self.authoring_generation_fingerprint, "authoring_generation_fingerprint")
        if not self.statistics_fingerprints or self.statistics_fingerprints != tuple(
            sorted(set(self.statistics_fingerprints))
        ):
            raise OnlyResearchEvaluationError(
                "EVALUATION_SUBJECT_INVALID", "Statistics identities must be non-empty, canonical, and unique"
            )
        for fingerprint in self.statistics_fingerprints:
            _sha(fingerprint, "statistics_fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "graph_fingerprint": self.graph_fingerprint,
            "candidate_node_fingerprint": self.candidate_node_fingerprint,
            "output_name": self.output_name,
            "candidate_fingerprint": self.candidate_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "specification_fingerprint": self.specification_fingerprint,
            "result_plan_fingerprint": self.result_plan_fingerprint,
            "statistics_fingerprints": list(self.statistics_fingerprints),
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "authoring_generation_fingerprint": self.authoring_generation_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyExactEvaluationIntentSubjectV1:
        expected = {
            "schema_version",
            "graph_fingerprint",
            "candidate_node_fingerprint",
            "output_name",
            "candidate_fingerprint",
            "dataset_snapshot_fingerprint",
            "specification_fingerprint",
            "result_plan_fingerprint",
            "statistics_fingerprints",
            "catalog_generation_fingerprint",
            "runtime_generation_fingerprint",
            "authoring_generation_fingerprint",
        }
        statistics = payload.get("statistics_fingerprints")
        if set(payload) != expected or payload.get("schema_version") != 1 or not isinstance(statistics, list):
            raise OnlyResearchEvaluationError(
                "EVALUATION_SUBJECT_SCHEMA_UNSUPPORTED", "Evaluation Subject fields or schema differ"
            )
        return cls(
            cast(str, payload["graph_fingerprint"]),
            cast(str, payload["candidate_node_fingerprint"]),
            cast(str, payload["output_name"]),
            cast(str, payload["candidate_fingerprint"]),
            cast(str, payload["dataset_snapshot_fingerprint"]),
            cast(str, payload["specification_fingerprint"]),
            cast(str, payload["result_plan_fingerprint"]),
            tuple(cast(list[str], statistics)),
            cast(str, payload["catalog_generation_fingerprint"]),
            cast(str, payload["runtime_generation_fingerprint"]),
            cast(str | None, payload["authoring_generation_fingerprint"]),
        )

    @property
    def subject_fingerprint(self) -> str:
        return only_canonical_fingerprint({"domain": _FINGERPRINT_DOMAIN, **self.to_dict()})


class OnlyExactAuthoringGenerationReader(Protocol):
    def load_descriptor_verified(self, fingerprint: str) -> Mapping[str, object]: ...


class _RuntimeResolutionReader(Protocol):
    def resolve(self, runtime_generation_fingerprint: str, specification: OnlyResearchSpecification) -> object: ...


class OnlyExactEvaluationIntentResolverV1:
    """Project verified owner facts into one prospective evaluation subject."""

    def __init__(
        self,
        *,
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
        runtime_resolution: _RuntimeResolutionReader,
        authoring_generations: OnlyExactAuthoringGenerationReader | None = None,
    ) -> None:
        self._runtime_generations = runtime_generations
        self._runtime_resolution = runtime_resolution
        self._authoring_generations = authoring_generations

    def resolve(
        self,
        specification: OnlyResearchSpecification,
        *,
        runtime_work_id: str,
        authoring_provenance: OnlyResearchAuthoringProvenance | None = None,
    ) -> OnlyExactEvaluationIntentSubjectV1:
        subjects = self.resolve_all(
            specification,
            runtime_work_id=runtime_work_id,
            authoring_provenance=authoring_provenance,
        )
        if len(subjects) != 1:
            raise OnlyResearchEvaluationError(
                "EVALUATION_SUBJECT_AMBIGUOUS", "scientific Specification resolves more than one Candidate"
            )
        return subjects[0]

    def resolve_all(
        self,
        specification: OnlyResearchSpecification,
        *,
        runtime_work_id: str,
        authoring_provenance: OnlyResearchAuthoringProvenance | None = None,
    ) -> tuple[OnlyExactEvaluationIntentSubjectV1, ...]:
        from onlyalpha.research.run.evidence import OnlyResearchAdmissionResolutionEvidence
        from onlyalpha.research.specification.model import (
            RESEARCH_SPECIFICATION_SCIENTIFIC_SCHEMA_VERSION,
            OnlyResearchSpecification,
        )

        strict = OnlyResearchSpecification.from_dict(specification.to_dict())
        if strict.schema_version != RESEARCH_SPECIFICATION_SCIENTIFIC_SCHEMA_VERSION or strict.evidence is None:
            raise OnlyResearchEvaluationError(
                "EVALUATION_SUBJECT_SCHEMA_UNSUPPORTED", "a scientific Research Specification V2 is required"
            )
        try:
            binding = self._runtime_generations.require_work_binding(runtime_work_id)
            runtime = _sha(getattr(binding, "runtime_generation_fingerprint", None), "runtime generation")
            if getattr(binding, "work_id", runtime_work_id) != runtime_work_id:
                raise OnlyResearchEvaluationError(
                    "EVALUATION_SUBJECT_BINDING_MISMATCH", "Runtime work binding names another work item"
                )
            manifest = self._runtime_generations.require_runtime_generation(runtime)
            if getattr(manifest, "runtime_generation_fingerprint", None) != runtime:
                raise OnlyResearchEvaluationError(
                    "EVALUATION_SUBJECT_BINDING_MISMATCH", "Runtime manifest identity differs"
                )
            catalog = _sha(getattr(manifest, "catalog_generation_fingerprint", None), "Catalog generation")
            evidence = self._runtime_resolution.resolve(runtime, strict)
            if not isinstance(evidence, OnlyResearchAdmissionResolutionEvidence):
                raise OnlyResearchEvaluationError(
                    "EVALUATION_SUBJECT_AUTHORITY_CORRUPT", "Runtime authority returned untyped admission evidence"
                )
        except OnlyResearchEvaluationError:
            raise
        except Exception as exc:
            raise OnlyResearchEvaluationError(
                "EVALUATION_SUBJECT_AUTHORITY_MISSING", "exact Runtime evaluation authority is unavailable"
            ) from exc

        authoring = self._verify_authoring(authoring_provenance, catalog)
        return _subjects_from_evidence(strict, evidence, catalog, runtime, authoring)

    def _verify_authoring(self, provenance: OnlyResearchAuthoringProvenance | None, catalog: str) -> str | None:
        if provenance is None:
            return None
        if self._authoring_generations is None:
            raise OnlyResearchEvaluationError(
                "EVALUATION_SUBJECT_AUTHORITY_MISSING", "exact Authoring Generation authority is unavailable"
            )
        identity = provenance.execution_generation_fingerprint
        try:
            descriptor = self._authoring_generations.load_descriptor_verified(identity)
            payload = descriptor.get("provenance")
            if (
                descriptor.get("execution_generation_fingerprint") != identity
                or not isinstance(payload, Mapping)
                or dict(payload) != provenance.identity_dict()
                or provenance.catalog_generation_fingerprint != catalog
            ):
                raise ValueError("Authoring Generation binding differs")
        except Exception as exc:
            raise OnlyResearchEvaluationError(
                "EVALUATION_SUBJECT_AUTHORITY_CORRUPT", "exact Authoring Generation proof differs"
            ) from exc
        return identity


def _subjects_from_evidence(
    specification: OnlyResearchSpecification,
    evidence: object,
    catalog: str,
    runtime: str,
    authoring: str | None,
) -> tuple[OnlyExactEvaluationIntentSubjectV1, ...]:
    to_dict = getattr(evidence, "to_dict", None)
    if not callable(to_dict):
        raise OnlyResearchEvaluationError(
            "EVALUATION_SUBJECT_AUTHORITY_CORRUPT", "admission authority returned invalid evidence"
        )
    payload = to_dict()
    if not isinstance(payload, Mapping):
        raise OnlyResearchEvaluationError(
            "EVALUATION_SUBJECT_AUTHORITY_CORRUPT", "admission authority returned malformed evidence"
        )
    if (
        payload.get("schema_version") != 2
        or payload.get("specification_fingerprint") != specification.specification_fingerprint
    ):
        raise OnlyResearchEvaluationError(
            "EVALUATION_SUBJECT_BINDING_MISMATCH", "admission evidence does not name the scientific Specification"
        )
    candidates_raw = cast(list[object], payload["candidates"])
    candidates = tuple(cast(Mapping[str, object], item) for item in candidates_raw)
    candidate_id = specification.evidence.candidate_calculation_id  # type: ignore[union-attr]
    selected = tuple(
        item
        for item in candidates
        if item.get("calculation_id") == candidate_id and item.get("candidate_fingerprint") is not None
    )
    if not selected:
        raise OnlyResearchEvaluationError(
            "EVALUATION_SUBJECT_UNRESOLVED", "scientific Specification resolves no Candidate"
        )
    subjects = tuple(
        _candidate_subject(specification, candidates, candidate, payload, catalog, runtime, authoring)
        for candidate in selected
    )
    canonical = tuple(sorted(subjects, key=lambda item: item.candidate_fingerprint))
    if len({item.candidate_fingerprint for item in canonical}) != len(canonical):
        raise OnlyResearchEvaluationError("EVALUATION_SUBJECT_AUTHORITY_CORRUPT", "Candidate identities are duplicated")
    return canonical


def _candidate_subject(
    specification: OnlyResearchSpecification,
    candidates: tuple[Mapping[str, object], ...],
    candidate: Mapping[str, object],
    evidence: Mapping[str, object],
    catalog: str,
    runtime: str,
    authoring: str | None,
) -> OnlyExactEvaluationIntentSubjectV1:
    candidate_id = specification.evidence.candidate_calculation_id  # type: ignore[union-attr]
    candidate_fingerprint = _sha(candidate.get("candidate_fingerprint"), "Candidate")
    node_fingerprints = candidate.get("node_fingerprints")
    if not isinstance(node_fingerprints, Mapping):
        raise OnlyResearchEvaluationError("EVALUATION_SUBJECT_AUTHORITY_CORRUPT", "Candidate node lineage is malformed")
    evaluated_outputs = {
        (node_fingerprints.get(item.feature.template_node_id), item.feature.output_name)
        for item in specification.statistics
        if item.feature.calculation_id == candidate_id
    }
    if len(evaluated_outputs) != 1:
        raise OnlyResearchEvaluationError(
            "EVALUATION_SUBJECT_AMBIGUOUS", "scientific Candidate does not resolve one evaluated output"
        )
    evaluated_node, evaluated_output = next(iter(evaluated_outputs))
    published = tuple(
        cast(Mapping[str, object], item)
        for item in cast(list[object], evidence["published_series"])
        if isinstance(item, Mapping)
        and item.get("candidate_fingerprint") == candidate_fingerprint
        and (item.get("node_fingerprint"), item.get("output_name")) == (evaluated_node, evaluated_output)
    )
    if len(published) != 1:
        raise OnlyResearchEvaluationError(
            "EVALUATION_SUBJECT_AMBIGUOUS", "scientific Candidate does not resolve one published output"
        )
    output = published[0]
    if output.get("calculation_fingerprint") != candidate.get("calculation_fingerprint"):
        raise OnlyResearchEvaluationError(
            "EVALUATION_SUBJECT_BINDING_MISMATCH", "published output does not belong to the Candidate"
        )
    return OnlyExactEvaluationIntentSubjectV1(
        _sha(candidate.get("graph_fingerprint"), "Graph"),
        _sha(output.get("node_fingerprint"), "candidate node"),
        cast(str, output.get("output_name")),
        candidate_fingerprint,
        specification.dataset_snapshot_fingerprint,
        specification.specification_fingerprint,
        _sha(evidence.get("research_result_plan_fingerprint"), "Result Plan"),
        _candidate_statistics(specification, candidates, candidate_fingerprint, evidence),
        catalog,
        runtime,
        authoring,
    )


def _candidate_statistics(
    specification: OnlyResearchSpecification,
    candidates: tuple[Mapping[str, object], ...],
    candidate_fingerprint: str,
    evidence: Mapping[str, object],
) -> tuple[str, ...]:
    by_calculation: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for candidate in candidates:
        calculation_id = candidate.get("calculation_id")
        if not isinstance(calculation_id, str):
            raise OnlyResearchEvaluationError("EVALUATION_SUBJECT_AUTHORITY_CORRUPT", "Candidate lineage is malformed")
        by_calculation[calculation_id].append(candidate)
    raw_statistics = cast(list[object], evidence["statistics_fingerprints"])
    cursor = 0
    selected: list[str] = []
    for spec in specification.statistics:
        feature = by_calculation.get(spec.feature.calculation_id, [])
        target = by_calculation.get(spec.target.calculation_id, [])
        if not feature or not target or (len(feature) > 1 and len(target) > 1):
            raise OnlyResearchEvaluationError(
                "EVALUATION_SUBJECT_AUTHORITY_CORRUPT", "Statistics expansion differs from admission evidence"
            )
        count = max(len(feature), len(target))
        if cursor + count > len(raw_statistics):
            raise OnlyResearchEvaluationError(
                "EVALUATION_SUBJECT_AUTHORITY_CORRUPT", "Statistics admission evidence is incomplete"
            )
        for index in range(count):
            feature_item = feature[0 if len(feature) == 1 else index]
            target_item = target[0 if len(target) == 1 else index]
            fingerprint = _sha(raw_statistics[cursor + index], "Statistics")
            if candidate_fingerprint in {
                feature_item.get("candidate_fingerprint"),
                target_item.get("candidate_fingerprint"),
            }:
                selected.append(fingerprint)
        cursor += count
    if cursor != len(raw_statistics):
        raise OnlyResearchEvaluationError(
            "EVALUATION_SUBJECT_AUTHORITY_CORRUPT", "Statistics admission evidence has unmatched members"
        )
    return tuple(sorted(selected))


__all__ = [
    "OnlyExactAuthoringGenerationReader",
    "OnlyExactEvaluationIntentResolverV1",
    "OnlyExactEvaluationIntentSubjectV1",
]
