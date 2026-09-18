"""Programmatic durable Research Run admission service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import cast

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.dataset import (
    OnlyResearchDatasetCorruptError,
    OnlyResearchDatasetNotFoundError,
    OnlyResearchDatasetSnapshotStore,
)
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.specification.errors import OnlyResearchSpecificationError
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.specification.resolver import (
    OnlyResearchSpecificationResolution,
    OnlyResearchSpecificationResolver,
)

from .errors import OnlyResearchRunAdmissionError
from .evidence import OnlyResearchAdmissionResolutionEvidence, only_research_admission_resolution_fingerprint
from .generation import OnlyResearchAuthoringGenerationResolver
from .model import OnlyResearchRun, OnlyResearchRunId


class OnlyResearchRunAdmissionService:
    def __init__(
        self,
        *,
        resolver: OnlyResearchSpecificationResolver,
        dataset_store: OnlyResearchDatasetSnapshotStore,
        now_utc: Callable[[], datetime],
        run_id_factory: Callable[[], OnlyResearchRunId] = OnlyResearchRunId.new,
        authoring_generation_resolver: OnlyResearchAuthoringGenerationResolver | None = None,
    ) -> None:
        self._resolver = resolver
        self._dataset_store = dataset_store
        self._now_utc = now_utc
        self._run_id_factory = run_id_factory
        self._authoring_generation_resolver = authoring_generation_resolver

    def prepare(
        self,
        specification: OnlyResearchSpecification,
        *,
        authoring_generation_fingerprint: str | None = None,
        exact_run_id: OnlyResearchRunId | None = None,
        exact_admission_evidence: OnlyResearchAdmissionResolutionEvidence | None = None,
    ) -> OnlyResearchRun:
        """Prepare a QUEUED Run without making a durable acknowledgement."""

        return self.prepare_with_evidence(
            specification,
            authoring_generation_fingerprint=authoring_generation_fingerprint,
            exact_run_id=exact_run_id,
            exact_admission_evidence=exact_admission_evidence,
        )[0]

    def prepare_with_evidence(
        self,
        specification: OnlyResearchSpecification,
        *,
        authoring_generation_fingerprint: str | None = None,
        exact_run_id: OnlyResearchRunId | None = None,
        exact_admission_evidence: OnlyResearchAdmissionResolutionEvidence | None = None,
    ) -> tuple[OnlyResearchRun, OnlyResearchAdmissionResolutionEvidence]:
        """Prepare a Run and return the same typed evidence admitted into it."""

        try:
            strict = OnlyResearchSpecification.from_dict(specification.to_dict())
            provenance = self._load_authoring_provenance(authoring_generation_fingerprint)
            if exact_admission_evidence is None:
                evidence = OnlyResearchAdmissionResolutionEvidence.from_resolution(
                    self._resolve(strict, authoring_generation_fingerprint)
                )
            else:
                # Internal Product orchestration only: never part of Product/API intent.
                if exact_run_id is None or not isinstance(
                    exact_admission_evidence, OnlyResearchAdmissionResolutionEvidence
                ):
                    raise OnlyResearchRunAdmissionError(
                        "Exact Runtime evidence requires a derived Run identity",
                        code="RESEARCH_ADMISSION_EVIDENCE_INVALID",
                    )
                evidence = OnlyResearchAdmissionResolutionEvidence.from_dict(exact_admission_evidence.to_dict())
                if evidence.specification_fingerprint != strict.specification_fingerprint:
                    raise OnlyResearchRunAdmissionError(
                        "Admission evidence names another Specification",
                        code="RESEARCH_ADMISSION_EVIDENCE_SPECIFICATION_MISMATCH",
                    )
                if provenance is not None:
                    # A Run may already carry both independent generation bindings.
                    # Preserve authoring provenance admission, but never replace the
                    # exact Runtime computation with its result or a current Resolver.
                    authoring = OnlyResearchAdmissionResolutionEvidence.from_resolution(
                        self._resolve(strict, authoring_generation_fingerprint)
                    )
                    if authoring.fingerprint != evidence.fingerprint:
                        raise OnlyResearchRunAdmissionError(
                            "Authoring and exact Runtime generation admission semantics differ",
                            code="RESEARCH_EXECUTION_GENERATION_MISMATCH",
                        )
            self._dataset_store.load_verified_table(strict.dataset_snapshot_fingerprint)
            run = OnlyResearchRun.queued(
                run_id=self._run_id_factory() if exact_run_id is None else exact_run_id,
                specification=strict,
                canonical_specification_payload=only_canonical_json(strict.to_dict()),
                admission_resolution_fingerprint=evidence.fingerprint,
                queued_at=self._now_utc(),
                authoring_provenance=provenance,
            )
        except OnlyResearchRunAdmissionError:
            raise
        except OnlyResearchSpecificationError as exc:
            raise OnlyResearchRunAdmissionError(exc.detail, code=exc.code) from exc
        except OnlyResearchDatasetNotFoundError as exc:
            raise OnlyResearchRunAdmissionError(
                "Research Dataset Snapshot was not found", code="RESEARCH_DATASET_NOT_FOUND"
            ) from exc
        except OnlyResearchDatasetCorruptError as exc:
            raise OnlyResearchRunAdmissionError(
                "Research Dataset Snapshot verification failed", code="RESEARCH_DATASET_CORRUPT"
            ) from exc
        except Exception as exc:
            raise OnlyResearchRunAdmissionError(f"admission failed: {type(exc).__name__}") from exc
        return run, evidence

    def verify_resolution(self, run: OnlyResearchRun) -> None:
        current = only_research_admission_resolution_fingerprint(
            self._resolve(run.specification, run.authoring_generation_fingerprint)
        )
        if current != run.admission_resolution_fingerprint:
            raise OnlyResearchRunAdmissionError("admission resolution evidence mismatch")

    def _resolve(
        self,
        specification: OnlyResearchSpecification,
        authoring_generation_fingerprint: str | None,
    ) -> OnlyResearchSpecificationResolution:
        if authoring_generation_fingerprint is None:
            return self._resolver.resolve(specification)
        if self._authoring_generation_resolver is None:
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation is unavailable",
                code="RESEARCH_EXECUTION_GENERATION_UNAVAILABLE",
            )
        try:
            return self._authoring_generation_resolver.resolve(authoring_generation_fingerprint, specification)
        except OnlyResearchRunAdmissionError:
            raise
        except Exception as exc:
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation verification failed",
                code=cast(str, getattr(exc, "code", "RESEARCH_EXECUTION_GENERATION_MISMATCH")),
            ) from exc

    def _load_authoring_provenance(
        self, authoring_generation_fingerprint: str | None
    ) -> OnlyResearchAuthoringProvenance | None:
        if authoring_generation_fingerprint is None:
            return None
        if self._authoring_generation_resolver is None:
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation is unavailable",
                code="RESEARCH_EXECUTION_GENERATION_UNAVAILABLE",
            )
        try:
            provenance = self._authoring_generation_resolver.load_verified(authoring_generation_fingerprint)
        except OnlyResearchRunAdmissionError:
            raise
        except Exception as exc:
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation verification failed",
                code=cast(str, getattr(exc, "code", "RESEARCH_EXECUTION_GENERATION_MISMATCH")),
            ) from exc
        if provenance.execution_generation_fingerprint != authoring_generation_fingerprint:
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation identity differs",
                code="RESEARCH_EXECUTION_GENERATION_MISMATCH",
            )
        return provenance


__all__ = ["OnlyResearchRunAdmissionService"]
