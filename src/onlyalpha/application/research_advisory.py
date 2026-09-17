"""Read-only Product Query composition for structured near-duplicate advice."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.kernel.query import OnlyProductQuery
from onlyalpha.research.evaluation.subject import (
    OnlyExactEvaluationIntentResolverV1,
    OnlyExactEvaluationIntentSubjectV1,
)
from onlyalpha.research.memory.advisory import (
    REPRESENTATION_SCHEMA_VERSION,
    STRUCTURED_ALGORITHM_ID,
    STRUCTURED_ALGORITHM_VERSION,
    OnlyExperimentMemoryAdvisoryProjectionBuilder,
    OnlyNearDuplicateQueryV1,
    OnlyNearDuplicateResultStatus,
    OnlyNearDuplicateResultV1,
    OnlyNearDuplicateThresholdPolicyV1,
    OnlyResearchAdvisorySourceRefV1,
    OnlyResearchAdvisoryUnavailableError,
    OnlyVerifiedResearchAdvisorySnapshotV1,
    only_build_research_advisory_representation,
    only_query_near_duplicates,
)
from onlyalpha.research.memory.source_manifest import OnlyMemoryProjectionError
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.specification.resolver import (
    OnlyResearchSpecificationResolution,
    OnlyResearchSpecificationResolver,
)

BUNDLE_SCHEMA_VERSION = 1


class OnlyResearchAdvisoryProductError(RuntimeError):
    code = "RESEARCH_ADVISORY_PRODUCT_ERROR"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class OnlyResearchAdvisoryRequestInvalid(OnlyResearchAdvisoryProductError):
    code = "RESEARCH_ADVISORY_REQUEST_INVALID"


class OnlyResearchAdvisoryRevisionNotFound(OnlyResearchAdvisoryProductError):
    code = "RESEARCH_ADVISORY_REVISION_NOT_FOUND"


class OnlyResearchAdvisoryAuthorityUnavailable(OnlyResearchAdvisoryProductError):
    code = "RESEARCH_ADVISORY_AUTHORITY_UNAVAILABLE"


class OnlyResearchAdvisoryProjectionCorrupt(OnlyResearchAdvisoryProductError):
    code = "RESEARCH_ADVISORY_PROJECTION_CORRUPT"


class OnlyResearchAdvisoryUnsupported(OnlyResearchAdvisoryProductError):
    code = "RESEARCH_ADVISORY_UNSUPPORTED"


class OnlyResearchAdvisoryInvariantViolation(OnlyResearchAdvisoryProductError):
    code = "RESEARCH_ADVISORY_INVARIANT_VIOLATION"


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is required")
    return value


@dataclass(frozen=True, slots=True)
class OnlyGetResearchNearDuplicateAdvisoryV1(OnlyProductQuery):
    """A Product read intent; the caller supplies no scientific identity."""

    specification: OnlyResearchSpecification
    runtime_work_id: str
    projection_revision: str | None = None
    limit: int = 10
    authoring_provenance: OnlyResearchAuthoringProvenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.specification, OnlyResearchSpecification):
            raise TypeError("near-duplicate query requires a Research Specification")
        object.__setattr__(self, "specification", OnlyResearchSpecification.from_dict(self.specification.to_dict()))
        _text(self.runtime_work_id, "runtime_work_id")
        if self.projection_revision is not None:
            _sha(self.projection_revision, "projection_revision")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("near-duplicate result limit is invalid")
        if self.authoring_provenance is not None and not isinstance(
            self.authoring_provenance, OnlyResearchAuthoringProvenance
        ):
            raise TypeError("authoring_provenance is invalid")


@dataclass(frozen=True, slots=True)
class OnlyResearchNearDuplicateAdvisoryEntryV1:
    subject_fingerprint: str
    representation_fingerprint: str
    result: OnlyNearDuplicateResultV1

    def __post_init__(self) -> None:
        _sha(self.subject_fingerprint, "subject_fingerprint")
        _sha(self.representation_fingerprint, "representation_fingerprint")
        if not isinstance(self.result, OnlyNearDuplicateResultV1):
            raise TypeError("advisory entry result is required")

    def to_dict(self) -> dict[str, object]:
        return {
            "subject_fingerprint": self.subject_fingerprint,
            "representation_fingerprint": self.representation_fingerprint,
            "result": self.result.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: object) -> OnlyResearchNearDuplicateAdvisoryEntryV1:
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "subject_fingerprint",
                "representation_fingerprint",
                "result",
            }
            or not isinstance(payload["result"], dict)
        ):
            raise ValueError("advisory entry fields are invalid")
        return cls(
            cast(str, payload["subject_fingerprint"]),
            cast(str, payload["representation_fingerprint"]),
            OnlyNearDuplicateResultV1.from_dict(cast(dict[str, object], payload["result"])),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchNearDuplicateAdvisoryBundleV1:
    specification_fingerprint: str
    projection_revision: str
    source_cut_fingerprint: str
    index_build_revision: str
    requested_result_limit: int
    retrieval_algorithm_id: str
    retrieval_algorithm_version: str
    threshold_policy: OnlyNearDuplicateThresholdPolicyV1
    entries: tuple[OnlyResearchNearDuplicateAdvisoryEntryV1, ...]
    schema_version: int = BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _sha(self.specification_fingerprint, "specification_fingerprint")
        _sha(self.projection_revision, "projection_revision")
        _sha(self.source_cut_fingerprint, "source_cut_fingerprint")
        _sha(self.index_build_revision, "index_build_revision")
        if (
            self.schema_version != BUNDLE_SCHEMA_VERSION
            or self.retrieval_algorithm_id != STRUCTURED_ALGORITHM_ID
            or self.retrieval_algorithm_version != STRUCTURED_ALGORITHM_VERSION
            or not isinstance(self.threshold_policy, OnlyNearDuplicateThresholdPolicyV1)
            or not self.entries
            or type(self.requested_result_limit) is not int
            or not 1 <= self.requested_result_limit <= 100
        ):
            raise ValueError("near-duplicate advisory bundle is unsupported")
        if self.entries != tuple(sorted(self.entries, key=lambda item: item.subject_fingerprint)):
            raise ValueError("advisory entries are not ordered by subject fingerprint")
        if len({item.subject_fingerprint for item in self.entries}) != len(self.entries):
            raise ValueError("advisory entries contain duplicate subjects")
        for entry in self.entries:
            result = entry.result
            if (
                result.projection_revision != self.projection_revision
                or result.source_cut_fingerprint != self.source_cut_fingerprint
                or result.retrieval_algorithm_id != self.retrieval_algorithm_id
                or result.retrieval_algorithm_version != self.retrieval_algorithm_version
                or result.threshold_policy_id != self.threshold_policy.policy_id
                or result.threshold_policy_version != self.threshold_policy.policy_version
                or result.threshold_policy_fingerprint != self.threshold_policy.policy_fingerprint
                or result.index_build_revision != self.index_build_revision
            ):
                raise ValueError("advisory bundle entries mix query context")
            expected_query = OnlyNearDuplicateQueryV1(
                entry.representation_fingerprint,
                self.projection_revision,
                self.source_cut_fingerprint,
                self.index_build_revision,
                self.threshold_policy.policy_fingerprint,
                self.requested_result_limit,
            )
            if expected_query.query_fingerprint != result.query_fingerprint:
                raise ValueError("advisory entry result does not bind its representation query")

    @property
    def bundle_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    @property
    def threshold_policy_id(self) -> str:
        return self.threshold_policy.policy_id

    @property
    def threshold_policy_version(self) -> str:
        return self.threshold_policy.policy_version

    @property
    def threshold_policy_fingerprint(self) -> str:
        return self.threshold_policy.policy_fingerprint

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "specification_fingerprint": self.specification_fingerprint,
            "projection_revision": self.projection_revision,
            "source_cut_fingerprint": self.source_cut_fingerprint,
            "index_build_revision": self.index_build_revision,
            "requested_result_limit": self.requested_result_limit,
            "retrieval_algorithm_id": self.retrieval_algorithm_id,
            "retrieval_algorithm_version": self.retrieval_algorithm_version,
            "threshold_policy": self.threshold_policy.to_dict(),
            "entries": [item.to_dict() for item in self.entries],
        }
        if include_fingerprint:
            payload["bundle_fingerprint"] = self.bundle_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: object) -> OnlyResearchNearDuplicateAdvisoryBundleV1:
        expected = {
            "schema_version",
            "specification_fingerprint",
            "projection_revision",
            "source_cut_fingerprint",
            "index_build_revision",
            "requested_result_limit",
            "retrieval_algorithm_id",
            "retrieval_algorithm_version",
            "threshold_policy",
            "entries",
            "bundle_fingerprint",
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != expected
            or not isinstance(payload["threshold_policy"], dict)
            or not isinstance(payload["entries"], list)
            or any(not isinstance(item, dict) for item in cast(list[object], payload["entries"]))
        ):
            raise ValueError("near-duplicate advisory bundle fields are invalid")
        result = cls(
            cast(str, payload["specification_fingerprint"]),
            cast(str, payload["projection_revision"]),
            cast(str, payload["source_cut_fingerprint"]),
            cast(str, payload["index_build_revision"]),
            cast(int, payload["requested_result_limit"]),
            cast(str, payload["retrieval_algorithm_id"]),
            cast(str, payload["retrieval_algorithm_version"]),
            OnlyNearDuplicateThresholdPolicyV1.from_dict(cast(dict[str, object], payload["threshold_policy"])),
            tuple(
                OnlyResearchNearDuplicateAdvisoryEntryV1.from_dict(item)
                for item in cast(list[dict[str, object]], payload["entries"])
            ),
            cast(int, payload["schema_version"]),
        )
        if payload["bundle_fingerprint"] != result.bundle_fingerprint or result.to_dict() != payload:
            raise ValueError("near-duplicate advisory bundle fingerprint differs")
        return result


class OnlyResearchNearDuplicateQueryService:
    """Resolve exact subjects and expose only disposable advisory evidence."""

    def __init__(
        self,
        *,
        specification_resolver: OnlyResearchSpecificationResolver,
        subject_resolver: OnlyExactEvaluationIntentResolverV1,
        advisory_builder: OnlyExperimentMemoryAdvisoryProjectionBuilder,
        threshold_policy: OnlyNearDuplicateThresholdPolicyV1,
    ) -> None:
        self._specifications = specification_resolver
        self._subjects = subject_resolver
        self._advisory = advisory_builder
        self._policy = threshold_policy

    def get(self, query: OnlyGetResearchNearDuplicateAdvisoryV1) -> OnlyResearchNearDuplicateAdvisoryBundleV1:
        if not isinstance(query, OnlyGetResearchNearDuplicateAdvisoryV1):
            raise OnlyResearchAdvisoryRequestInvalid("near-duplicate service requires its Product Query")
        if query.limit > self._policy.maximum_results:
            raise OnlyResearchAdvisoryRequestInvalid("near-duplicate result limit exceeds the Product policy")
        specification = query.specification
        resolution = self._specifications.resolve(specification)
        subjects = self._subjects.resolve_all(
            specification,
            runtime_work_id=query.runtime_work_id,
            authoring_provenance=query.authoring_provenance,
        )
        try:
            self._validate_subjects(specification, subjects)
        except ValueError as exc:
            raise OnlyResearchAdvisoryInvariantViolation(str(exc)) from exc
        try:
            snapshot = (
                self._advisory.load_active_snapshot_verified()
                if query.projection_revision is None
                else self._advisory.load_snapshot_verified(query.projection_revision)
            )
        except OnlyResearchAdvisoryProductError:
            raise
        except OnlyResearchAdvisoryUnavailableError as exc:
            raise OnlyResearchAdvisoryAuthorityUnavailable(str(exc)) from exc
        except OnlyMemoryProjectionError as exc:
            code = str(exc)
            if code == "PROJECTION_NOT_FOUND":
                raise OnlyResearchAdvisoryRevisionNotFound(code) from exc
            if code == "PROJECTION_SCHEMA_UNSUPPORTED":
                raise OnlyResearchAdvisoryUnsupported(code) from exc
            raise OnlyResearchAdvisoryProjectionCorrupt(code) from exc
        try:
            entries = tuple(
                sorted(
                    (self._entry(specification, resolution, subject, snapshot, query.limit) for subject in subjects),
                    key=lambda item: item.subject_fingerprint,
                )
            )
            return OnlyResearchNearDuplicateAdvisoryBundleV1(
                specification.specification_fingerprint,
                snapshot.projection_revision,
                snapshot.source_cut_fingerprint,
                snapshot.index_build_revision,
                query.limit,
                STRUCTURED_ALGORITHM_ID,
                STRUCTURED_ALGORITHM_VERSION,
                self._policy,
                entries,
            )
        except OnlyResearchAdvisoryProductError:
            raise
        except ValueError as exc:
            raise OnlyResearchAdvisoryInvariantViolation(str(exc)) from exc

    @staticmethod
    def _validate_subjects(
        specification: OnlyResearchSpecification,
        subjects: Sequence[OnlyExactEvaluationIntentSubjectV1],
    ) -> None:
        if not subjects:
            raise ValueError("Research Specification resolves no exact subjects")
        fingerprints = tuple(item.subject_fingerprint for item in subjects)
        if any(
            not isinstance(item, OnlyExactEvaluationIntentSubjectV1)
            or item.specification_fingerprint != specification.specification_fingerprint
            for item in subjects
        ):
            raise ValueError("exact subject resolution is not bound to the Specification")
        if fingerprints != tuple(sorted(fingerprints)) or len(set(fingerprints)) != len(fingerprints):
            raise ValueError("exact subjects are not canonical and unique")

    def _entry(
        self,
        specification: OnlyResearchSpecification,
        resolution: OnlyResearchSpecificationResolution,
        subject: OnlyExactEvaluationIntentSubjectV1,
        snapshot: OnlyVerifiedResearchAdvisorySnapshotV1,
        limit: int,
    ) -> OnlyResearchNearDuplicateAdvisoryEntryV1:
        try:
            candidates = tuple(
                item
                for item in resolution.candidates
                if item.candidate_fingerprint == subject.candidate_fingerprint
                and item.graph_fingerprint == subject.graph_fingerprint
            )
            if len(candidates) != 1:
                raise ValueError("exact subject candidate graph is unavailable")
            source_ref = OnlyResearchAdvisorySourceRefV1(
                "PRODUCT_QUERY_CURRENT",
                f"research-specification/{specification.specification_fingerprint}/subject/{subject.subject_fingerprint}",
                f"PRODUCT_QUERY_CURRENT:{subject.subject_fingerprint}",
                snapshot.projection_revision,
            )
            current = only_build_research_advisory_representation(
                subject=subject,
                graph=candidates[0].graph,
                specification=specification,
                source_ref=source_ref,
                projection_revision=snapshot.projection_revision,
                source_cut_fingerprint=snapshot.source_cut_fingerprint,
            )
            near_query = OnlyNearDuplicateQueryV1(
                current.representation_fingerprint,
                snapshot.projection_revision,
                snapshot.source_cut_fingerprint,
                snapshot.index_build_revision,
                self._policy.policy_fingerprint,
                limit,
            )
            result = only_query_near_duplicates(
                current=current,
                query=near_query,
                index=snapshot.index,
                policy=self._policy,
                source_verifier=snapshot,
            )
            return OnlyResearchNearDuplicateAdvisoryEntryV1(
                subject.subject_fingerprint,
                current.representation_fingerprint,
                result,
            )
        except OnlyResearchAdvisoryUnavailableError:
            return self._unavailable_entry(subject, snapshot, limit, "CURRENT_REPRESENTATION_UNAVAILABLE")

    def _unavailable_entry(
        self,
        subject: OnlyExactEvaluationIntentSubjectV1,
        snapshot: OnlyVerifiedResearchAdvisorySnapshotV1,
        limit: int,
        failure_code: str,
    ) -> OnlyResearchNearDuplicateAdvisoryEntryV1:
        representation_fingerprint = only_canonical_fingerprint(
            {"domain": "ONLYALPHA_PRODUCT_QUERY_CURRENT_SUBJECT_V1", "subject_fingerprint": subject.subject_fingerprint}
        )
        near_query = OnlyNearDuplicateQueryV1(
            representation_fingerprint,
            snapshot.projection_revision,
            snapshot.source_cut_fingerprint,
            snapshot.index_build_revision,
            self._policy.policy_fingerprint,
            limit,
        )
        result = OnlyNearDuplicateResultV1(
            near_query.query_fingerprint,
            snapshot.projection_revision,
            snapshot.source_cut_fingerprint,
            REPRESENTATION_SCHEMA_VERSION,
            STRUCTURED_ALGORITHM_ID,
            STRUCTURED_ALGORITHM_VERSION,
            self._policy.policy_id,
            self._policy.policy_version,
            self._policy.policy_fingerprint,
            snapshot.index_build_revision,
            OnlyNearDuplicateResultStatus.ADVISORY_UNAVAILABLE,
            (),
            failure_code,
        )
        return OnlyResearchNearDuplicateAdvisoryEntryV1(subject.subject_fingerprint, representation_fingerprint, result)


__all__ = [name for name in globals() if name.startswith("Only")]
