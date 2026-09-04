"""Programmatic durable Research Run admission service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

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
from .evidence import only_research_admission_resolution_fingerprint
from .generation import OnlyResearchAuthoringGenerationResolver
from .model import OnlyResearchRun, OnlyResearchRunId
from .store import OnlyResearchRunStore


class OnlyResearchRunAdmissionService:
    def __init__(
        self,
        *,
        resolver: OnlyResearchSpecificationResolver,
        dataset_store: OnlyResearchDatasetSnapshotStore,
        run_store: OnlyResearchRunStore,
        now_utc: Callable[[], datetime],
        run_id_factory: Callable[[], OnlyResearchRunId] = OnlyResearchRunId.new,
        authoring_generation_resolver: OnlyResearchAuthoringGenerationResolver | None = None,
    ) -> None:
        self._resolver = resolver
        self._dataset_store = dataset_store
        self._run_store = run_store
        self._now_utc = now_utc
        self._run_id_factory = run_id_factory
        self._authoring_generation_resolver = authoring_generation_resolver

    def submit(
        self, specification: OnlyResearchSpecification, provenance: OnlyResearchAuthoringProvenance | None = None
    ) -> OnlyResearchRun:
        return self._run_store.create_queued(self.prepare(specification, provenance=provenance))

    def prepare(
        self, specification: OnlyResearchSpecification, *, provenance: OnlyResearchAuthoringProvenance | None = None
    ) -> OnlyResearchRun:
        """Prepare a QUEUED Run without making a durable acknowledgement."""

        try:
            strict = OnlyResearchSpecification.from_dict(specification.to_dict())
            resolution = self._resolve(strict, provenance)
            self._dataset_store.load_verified_table(strict.dataset_snapshot_fingerprint)
            run = OnlyResearchRun.queued(
                run_id=self._run_id_factory(),
                specification=strict,
                canonical_specification_payload=only_canonical_json(strict.to_dict()),
                admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
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
        return run

    def verify_resolution(self, run: OnlyResearchRun) -> None:
        current = only_research_admission_resolution_fingerprint(
            self._resolve(run.specification, run.authoring_provenance)
        )
        if current != run.admission_resolution_fingerprint:
            raise OnlyResearchRunAdmissionError("admission resolution evidence mismatch")

    def _resolve(
        self,
        specification: OnlyResearchSpecification,
        provenance: OnlyResearchAuthoringProvenance | None,
    ) -> OnlyResearchSpecificationResolution:
        if provenance is None:
            return self._resolver.resolve(specification)
        if self._authoring_generation_resolver is None:
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation is unavailable",
                code="RESEARCH_EXECUTION_GENERATION_UNAVAILABLE",
            )
        try:
            return self._authoring_generation_resolver.resolve(provenance, specification)
        except OnlyResearchRunAdmissionError:
            raise
        except Exception as exc:
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation verification failed",
                code="RESEARCH_EXECUTION_GENERATION_MISMATCH",
            ) from exc


__all__ = ["OnlyResearchRunAdmissionService"]
