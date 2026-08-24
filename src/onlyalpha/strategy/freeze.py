"""The unique authoritative Research Candidate to Strategy Freeze boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import NoReturn, Protocol

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.dataset import OnlyVerifiedResearchDataset
from onlyalpha.research.result.result import OnlyResearchResult
from onlyalpha.research.run import OnlyResearchRun, OnlyResearchRunId, OnlyResearchRunState
from onlyalpha.research.specification.identity import only_research_candidate_fingerprint
from onlyalpha.research.specification.resolver import (
    OnlyResearchSignalLineage,
    OnlyResearchSpecificationResolver,
)
from onlyalpha.strategy.admission import OnlyStrategyTradingAdmissionService
from onlyalpha.strategy.errors import OnlyStrategyAdmissionError, OnlyStrategyFreezeError
from onlyalpha.strategy.revision import (
    OnlyStrategyMarketInputContract,
    OnlyStrategyRevision,
    OnlyStrategySignalBinding,
    OnlyStrategySignalSemantics,
    OnlyStrategyUniverse,
)
from onlyalpha.strategy.store import OnlyStrategyRevisionStore


class _ResearchRunStore(Protocol):
    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun: ...


class _ResearchResultStore(Protocol):
    def load_verified(self, research_result_fingerprint: str) -> OnlyResearchResult: ...


class _CalculationResultStore(Protocol):
    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult: ...


class _DatasetStore(Protocol):
    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset: ...


class OnlyStrategyFreezeDisposition(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True)
class OnlyStrategyFreezeRequest:
    research_run_id: OnlyResearchRunId
    candidate_fingerprint: str
    actor: str
    comment: str | None = None

    def __post_init__(self) -> None:
        _sha(self.candidate_fingerprint, "candidate_fingerprint")
        if not self.actor.strip():
            raise ValueError("Freeze actor is required")


@dataclass(frozen=True, slots=True)
class OnlyStrategyFreezeRecord:
    candidate_fingerprint: str
    research_result_fingerprint: str
    strategy_fingerprint: str
    admission_evidence_fingerprint: str
    equivalence_evidence_fingerprints: tuple[str, ...]
    actor: str
    created_at: datetime
    comment: str | None = None
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise ValueError("unsupported Strategy Freeze Record schema")
        for name in (
            "candidate_fingerprint",
            "research_result_fingerprint",
            "strategy_fingerprint",
            "admission_evidence_fingerprint",
        ):
            _sha(getattr(self, name), name)
        canonical = tuple(sorted(self.equivalence_evidence_fingerprints))
        if (
            not canonical
            or canonical != self.equivalence_evidence_fingerprints
            or len(canonical) != len(set(canonical))
        ):
            raise ValueError("Freeze equivalence evidence must be canonical, non-empty and unique")
        for value in canonical:
            _sha(value, "equivalence_evidence_fingerprint")
        if not self.actor.strip():
            raise ValueError("Freeze actor is required")
        _utc(self.created_at, "Freeze created_at")

    @property
    def record_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "candidate_fingerprint": self.candidate_fingerprint,
            "research_result_fingerprint": self.research_result_fingerprint,
            "strategy_fingerprint": self.strategy_fingerprint,
            "admission_evidence_fingerprint": self.admission_evidence_fingerprint,
            "equivalence_evidence_fingerprints": list(self.equivalence_evidence_fingerprints),
            "actor": self.actor,
            "created_at": self.created_at.isoformat(),
            "comment": self.comment,
        }
        if include_fingerprint:
            payload["record_fingerprint"] = self.record_fingerprint
        return payload


class OnlyStrategyCatalogWriter(Protocol):
    def ensure_strategy(self, strategy_fingerprint: str, schema_version: int) -> None: ...

    def find_freeze_relation(
        self,
        candidate_fingerprint: str,
        research_result_fingerprint: str,
        strategy_fingerprint: str,
    ) -> OnlyStrategyFreezeRecord | None: ...

    def append_freeze_record(self, record: OnlyStrategyFreezeRecord) -> OnlyStrategyFreezeRecord: ...


@dataclass(frozen=True, slots=True)
class OnlyStrategyFreezeOutcome:
    strategy_fingerprint: str
    disposition: OnlyStrategyFreezeDisposition
    freeze_record: OnlyStrategyFreezeRecord


class OnlyStrategyFreezeService:
    def __init__(
        self,
        *,
        runs: _ResearchRunStore,
        research_results: _ResearchResultStore,
        calculation_results: _CalculationResultStore,
        datasets: _DatasetStore,
        specification_resolver: OnlyResearchSpecificationResolver,
        admission: OnlyStrategyTradingAdmissionService,
        strategies: OnlyStrategyRevisionStore,
        catalog: OnlyStrategyCatalogWriter,
        audit_time: Callable[[], datetime],
    ) -> None:
        self._runs = runs
        self._research_results = research_results
        self._calculation_results = calculation_results
        self._datasets = datasets
        self._specification_resolver = specification_resolver
        self._admission = admission
        self._strategies = strategies
        self._catalog = catalog
        self._audit_time = audit_time

    def freeze(self, request: OnlyStrategyFreezeRequest) -> OnlyStrategyFreezeOutcome:
        try:
            try:
                run = self._runs.load(request.research_run_id)
            except Exception as exc:
                self._fail("CANDIDATE_NOT_FOUND", str(request.research_run_id), exc)
            if run.state is not OnlyResearchRunState.COMPLETED or run.research_result_fingerprint is None:
                self._fail("CANDIDATE_NOT_FOUND", "Research Run is not completed with exact Result evidence")
            # The immutable Result Store is addressed by the resolved Plan
            # identity, while the operational Run records the committed Result
            # content identity.  Re-resolve first, then verify both linkages.
            try:
                resolution = self._specification_resolver.resolve(run.specification)
            except Exception as exc:
                self._fail("CANDIDATE_IDENTITY_MISMATCH", "Research Specification cannot be resolved exactly", exc)
            try:
                result = self._research_results.load_verified(resolution.workload.result_plan.fingerprint)
            except Exception as exc:
                self._fail("RESEARCH_RESULT_CORRUPT", "exact Research Result verification failed", exc)
            if result.manifest.research_result_fingerprint != run.research_result_fingerprint:
                self._fail("RESEARCH_RESULT_CORRUPT", "Research Run and Result identity differ")
            candidates = tuple(
                item for item in resolution.candidates if item.candidate_fingerprint == request.candidate_fingerprint
            )
            if len(candidates) != 1:
                self._fail("CANDIDATE_NOT_FOUND", request.candidate_fingerprint)
            candidate = candidates[0]
            recomputed = only_research_candidate_fingerprint(
                run.specification_fingerprint,
                candidate.calculation_id,
                candidate.assignment,
                candidate.calculation_fingerprint,
            )
            if recomputed != request.candidate_fingerprint:
                self._fail("CANDIDATE_IDENTITY_MISMATCH", request.candidate_fingerprint)
            plan_candidate = next(
                (item for item in result.manifest.plan.candidates if item.candidate_fingerprint == recomputed),
                None,
            )
            if (
                plan_candidate is None
                or plan_candidate.candidate_calculation_id != candidate.calculation_id
                or dict(plan_candidate.assignment) != dict(candidate.assignment)
                or plan_candidate.calculation_fingerprint != candidate.calculation_fingerprint
                or plan_candidate.graph_fingerprint != candidate.graph_fingerprint
            ):
                self._fail("CANDIDATE_IDENTITY_MISMATCH", "Research Result Candidate linkage differs")
            signals = self._signals(resolution.signals, result, recomputed, candidate.calculation_fingerprint)
            try:
                calculation = self._calculation_results.load_verified(candidate.calculation_fingerprint)
            except Exception as exc:
                self._fail("CALCULATION_RESULT_CORRUPT", "exact Calculation Result verification failed", exc)
            calculation_reference = next(
                (
                    item
                    for item in result.manifest.calculation_results
                    if item.calculation_fingerprint == candidate.calculation_fingerprint
                ),
                None,
            )
            if (
                calculation_reference is None
                or calculation_reference.calculation_result_fingerprint
                != calculation.manifest.calculation_result_fingerprint
                or calculation.manifest.calculation_graph_fingerprint != candidate.graph_fingerprint
                or calculation.manifest.calculation_graph.to_dict() != candidate.graph.to_dict()
            ):
                self._fail("CALCULATION_RESULT_CORRUPT", "exact Candidate Calculation evidence differs")
            try:
                verified_dataset = self._datasets.load_verified_table(run.specification.dataset_snapshot_fingerprint)
            except Exception as exc:
                self._fail("RESEARCH_RESULT_CORRUPT", "exact Dataset Snapshot verification failed", exc)
            if (
                result.manifest.dataset_snapshot_fingerprint != verified_dataset.snapshot.snapshot_fingerprint
                or calculation.manifest.dataset_snapshot_fingerprint != verified_dataset.snapshot.snapshot_fingerprint
            ):
                self._fail("RESEARCH_RESULT_CORRUPT", "Dataset linkage differs across verified evidence")
            dataset_definition = verified_dataset.snapshot.definition
            market_input_contract = OnlyStrategyMarketInputContract(
                dataset_definition.bar_specification,
                dataset_definition.aggregation_source,
                dataset_definition.adjustment_type,
                dataset_definition.adjustment_reference,
            )
            admitted = self._admission.admit(candidate.graph, signals, market_input_contract)
            revision = OnlyStrategyRevision(
                OnlyStrategyUniverse(dataset_definition.instruments),
                market_input_contract,
                candidate.graph,
                admitted.implementation_bindings,
                signals,
            )
            fingerprint = str(revision.strategy_fingerprint)
            existed = self._strategies.exists(fingerprint)
            self._strategies.commit(revision)
            self._catalog.ensure_strategy(fingerprint, revision.schema_version)
            existing_relation = self._catalog.find_freeze_relation(
                recomputed,
                run.research_result_fingerprint,
                fingerprint,
            )
            if existing_relation is not None:
                return OnlyStrategyFreezeOutcome(fingerprint, OnlyStrategyFreezeDisposition.REUSED, existing_relation)
            created_at = self._audit_time()
            _utc(created_at, "Freeze audit time")
            record = self._catalog.append_freeze_record(
                OnlyStrategyFreezeRecord(
                    candidate_fingerprint=recomputed,
                    research_result_fingerprint=run.research_result_fingerprint,
                    strategy_fingerprint=fingerprint,
                    admission_evidence_fingerprint=admitted.admission_evidence_fingerprint,
                    equivalence_evidence_fingerprints=admitted.equivalence_evidence_fingerprints,
                    actor=request.actor,
                    created_at=created_at,
                    comment=request.comment,
                )
            )
            disposition = OnlyStrategyFreezeDisposition.REUSED if existed else OnlyStrategyFreezeDisposition.CREATED
            return OnlyStrategyFreezeOutcome(fingerprint, disposition, record)
        except OnlyStrategyFreezeError:
            raise
        except OnlyStrategyAdmissionError as exc:
            raise OnlyStrategyFreezeError(exc.code, exc.detail) from exc
        except Exception as exc:
            raise OnlyStrategyFreezeError("STRATEGY_FREEZE_FAILED", type(exc).__name__) from exc

    @staticmethod
    def _signals(
        resolved_signals: tuple[OnlyResearchSignalLineage, ...],
        result: OnlyResearchResult,
        candidate_fingerprint: str,
        calculation_fingerprint: str,
    ) -> OnlyStrategySignalSemantics:
        selected = tuple(
            item
            for item in resolved_signals
            if item.candidate_fingerprint == candidate_fingerprint
            and item.calculation_fingerprint == calculation_fingerprint
        )
        by_role = {str(item.role): item for item in selected}
        if set(by_role) != {"ELIGIBILITY", "ENTRY_SIGNAL", "EXIT_SIGNAL"} or len(selected) != 3:
            raise OnlyStrategyFreezeError("STRATEGY_NOT_TRADING_ADMISSIBLE", "exact ELIGIBILITY/ENTRY/EXIT required")
        result_signals = {
            (
                item.role,
                item.candidate_fingerprint,
                item.calculation_fingerprint,
                item.node_fingerprint,
                item.output_name,
            )
            for item in result.manifest.plan.signals
            if item.candidate_fingerprint == candidate_fingerprint
        }
        resolved = {
            (
                str(item.role),
                str(item.candidate_fingerprint),
                str(item.calculation_fingerprint),
                str(item.node_fingerprint),
                str(item.output_name),
            )
            for item in selected
        }
        if result_signals != resolved:
            raise OnlyStrategyFreezeError("RESEARCH_RESULT_CORRUPT", "Signal lineage differs from exact resolution")

        def binding(role: str) -> OnlyStrategySignalBinding:
            value = by_role[role]
            return OnlyStrategySignalBinding(
                str(value.node_fingerprint),
                str(value.output_name),
            )

        return OnlyStrategySignalSemantics(
            binding("ELIGIBILITY"),
            binding("ENTRY_SIGNAL"),
            binding("EXIT_SIGNAL"),
        )

    @staticmethod
    def _fail(code: str, detail: str, cause: Exception | None = None) -> NoReturn:
        error = OnlyStrategyFreezeError(code, detail)
        if cause is None:
            raise error
        raise error from cause


class OnlyInMemoryStrategyCatalog(OnlyStrategyCatalogWriter):
    """Deterministic adapter for unit composition; PostgreSQL owns deployed records."""

    def __init__(self) -> None:
        self.strategies: dict[str, int] = {}
        self.freeze_records: dict[str, OnlyStrategyFreezeRecord] = {}

    def ensure_strategy(self, strategy_fingerprint: str, schema_version: int) -> None:
        existing = self.strategies.get(strategy_fingerprint)
        if existing is not None and existing != schema_version:
            raise OnlyStrategyFreezeError("DETERMINISTIC_STRATEGY_CONFLICT", strategy_fingerprint)
        self.strategies[strategy_fingerprint] = schema_version

    def find_freeze_relation(
        self,
        candidate_fingerprint: str,
        research_result_fingerprint: str,
        strategy_fingerprint: str,
    ) -> OnlyStrategyFreezeRecord | None:
        return next(
            (
                item
                for item in self.freeze_records.values()
                if (
                    item.candidate_fingerprint,
                    item.research_result_fingerprint,
                    item.strategy_fingerprint,
                )
                == (candidate_fingerprint, research_result_fingerprint, strategy_fingerprint)
            ),
            None,
        )

    def append_freeze_record(self, record: OnlyStrategyFreezeRecord) -> OnlyStrategyFreezeRecord:
        existing = self.freeze_records.get(record.record_fingerprint)
        if existing is not None:
            return existing
        relation = self.find_freeze_relation(
            record.candidate_fingerprint,
            record.research_result_fingerprint,
            record.strategy_fingerprint,
        )
        if relation is not None:
            return relation
        self.freeze_records[record.record_fingerprint] = record
        return record


def _sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


def _utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")


__all__ = [name for name in globals() if name.startswith("Only")]
