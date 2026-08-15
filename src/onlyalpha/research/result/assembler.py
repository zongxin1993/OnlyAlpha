"""Research Result composition from verified Statistics authorities."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from onlyalpha.research.evaluation.result import OnlyResearchStatisticsResult

from .errors import OnlyResearchResultError
from .identity import only_research_result_content_fingerprint, only_research_result_fingerprint
from .plan import OnlyResearchResultPlan
from .result import OnlyResearchResult, OnlyResearchResultManifest, OnlyResearchStatisticsResultReference


class _StatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchStatisticsResult: ...


class OnlyResearchResultAssembler:
    def __init__(
        self,
        statistics_result_store: _StatisticsResultStore,
        *,
        audit_time: Callable[[], datetime],
    ) -> None:
        self._statistics_result_store = statistics_result_store
        self._audit_time = audit_time

    def assemble(self, plan: OnlyResearchResultPlan) -> OnlyResearchResult:
        if not isinstance(plan, OnlyResearchResultPlan):
            raise OnlyResearchResultError("RESEARCH_RESULT_INVALID", "Plan contract is invalid")
        references: list[OnlyResearchStatisticsResultReference] = []
        dataset: str | None = None
        try:
            for statistics_fingerprint in plan.statistics_fingerprints:
                upstream = self._statistics_result_store.load_verified(statistics_fingerprint)
                manifest = upstream.manifest
                if manifest.statistics_fingerprint != statistics_fingerprint:
                    raise ValueError("Statistics logical identity linkage mismatch")
                if dataset is None:
                    dataset = manifest.dataset_snapshot_fingerprint
                elif dataset != manifest.dataset_snapshot_fingerprint:
                    raise ValueError("Research Result Statistics Results must use one exact Dataset Snapshot")
                references.append(
                    OnlyResearchStatisticsResultReference(
                        statistics_fingerprint,
                        manifest.statistics_result_fingerprint,
                    )
                )
            created_at = self._audit_timestamp()
            canonical = tuple(sorted(references))
            content = only_research_result_content_fingerprint(tuple(item.to_dict() for item in canonical))
            result = only_research_result_fingerprint(plan.fingerprint, content)
            assert dataset is not None
            return OnlyResearchResult(
                OnlyResearchResultManifest(plan, plan.fingerprint, dataset, canonical, content, result, created_at)
            )
        except OnlyResearchResultError:
            raise
        except Exception as exc:
            raise OnlyResearchResultError("RESEARCH_RESULT_INVALID", str(exc)) from exc

    def _audit_timestamp(self) -> datetime:
        value = self._audit_time()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise OnlyResearchResultError("RESEARCH_RESULT_INVALID", "audit time must be timezone-aware UTC")
        return value
