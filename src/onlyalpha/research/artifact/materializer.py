"""Deterministic projection from verified Research authorities to an Artifact candidate."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from onlyalpha.research.evaluation.result import OnlyResearchStatisticRow, OnlyResearchStatisticsResult
from onlyalpha.research.evaluation.result_identity import (
    only_research_statistics_result_content_fingerprint,
    only_research_statistics_result_fingerprint,
)
from onlyalpha.research.result.identity import (
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.result.result import OnlyResearchResult

from .errors import OnlyResearchArtifactError
from .identity import only_research_artifact_content_fingerprint
from .model import OnlyResearchArtifactStatisticsEntry, OnlyResearchArtifactStatisticsRow


class _ResearchResultStore(Protocol):
    def load_verified(self, research_result_plan_fingerprint: str) -> OnlyResearchResult: ...


class _StatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchStatisticsResult: ...


@dataclass(frozen=True, slots=True)
class OnlyResearchArtifactCandidate:
    research_result_plan_fingerprint: str
    research_result_content_fingerprint: str
    research_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    statistics_results: tuple[OnlyResearchArtifactStatisticsEntry, ...]
    rows: tuple[OnlyResearchArtifactStatisticsRow, ...]
    artifact_content_fingerprint: str

    def __post_init__(self) -> None:
        values = (
            self.research_result_plan_fingerprint,
            self.research_result_content_fingerprint,
            self.research_result_fingerprint,
            self.dataset_snapshot_fingerprint,
            self.artifact_content_fingerprint,
        )
        if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in values):
            raise ValueError("Research Artifact candidate identities must be lower-case SHA256")
        if not isinstance(self.statistics_results, tuple) or not self.statistics_results:
            raise ValueError("Research Artifact candidate requires a Statistics catalog")
        identities = tuple(item.statistics_fingerprint for item in self.statistics_results)
        plan = OnlyResearchResultPlan(identities)
        if plan.fingerprint != self.research_result_plan_fingerprint:
            raise ValueError("Research Artifact candidate Research Result Plan mismatch")
        references = tuple(
            {
                "statistics_fingerprint": item.statistics_fingerprint,
                "statistics_result_fingerprint": item.statistics_result_fingerprint,
            }
            for item in self.statistics_results
        )
        content = only_research_result_content_fingerprint(references)
        if content != self.research_result_content_fingerprint:
            raise ValueError("Research Artifact candidate Research Result content mismatch")
        if only_research_result_fingerprint(plan.fingerprint, content) != self.research_result_fingerprint:
            raise ValueError("Research Artifact candidate Research Result mismatch")


class OnlyResearchArtifactMaterializer:
    def __init__(
        self,
        research_result_store: _ResearchResultStore,
        statistics_result_store: _StatisticsResultStore,
    ) -> None:
        self._research_result_store = research_result_store
        self._statistics_result_store = statistics_result_store

    def materialize(self, research_result_plan_fingerprint: str) -> OnlyResearchArtifactCandidate:
        try:
            research_result = self._research_result_store.load_verified(research_result_plan_fingerprint)
            research_manifest = research_result.manifest
            if research_manifest.research_result_plan_fingerprint != research_result_plan_fingerprint:
                raise ValueError("Research Result Plan identity mismatch")
            entries: list[OnlyResearchArtifactStatisticsEntry] = []
            rows: list[OnlyResearchArtifactStatisticsRow] = []
            for reference in research_manifest.statistics_results:
                statistics = self._statistics_result_store.load_verified(reference.statistics_fingerprint)
                manifest = statistics.manifest
                self._verify_statistics(reference.statistics_result_fingerprint, statistics)
                if manifest.dataset_snapshot_fingerprint != research_manifest.dataset_snapshot_fingerprint:
                    raise ValueError("Artifact members must use the Research Result Dataset Snapshot")
                entries.append(
                    OnlyResearchArtifactStatisticsEntry(
                        manifest.statistics_fingerprint,
                        manifest.statistics_result_fingerprint,
                        manifest.result_content_fingerprint,
                        manifest.plan,
                        manifest.row_count,
                        manifest.schema_version,
                    )
                )
                rows.extend(
                    OnlyResearchArtifactStatisticsRow(
                        manifest.statistics_fingerprint,
                        row.ts_event_ns,
                        row.statistic_value,
                        row.sample_count,
                        row.status,
                    )
                    for row in statistics.rows
                )
            catalog = tuple(entries)
            canonical_rows = tuple(rows)
            if catalog != tuple(sorted(catalog)) or canonical_rows != tuple(sorted(canonical_rows)):
                raise ValueError("Artifact projection is not canonical")
            artifact = only_research_artifact_content_fingerprint(
                research_manifest.research_result_fingerprint,
                research_manifest.dataset_snapshot_fingerprint,
                tuple(item.to_dict() for item in catalog),
            )
            return OnlyResearchArtifactCandidate(
                research_manifest.research_result_plan_fingerprint,
                research_manifest.research_result_content_fingerprint,
                research_manifest.research_result_fingerprint,
                research_manifest.dataset_snapshot_fingerprint,
                catalog,
                canonical_rows,
                artifact,
            )
        except OnlyResearchArtifactError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactError("ARTIFACT_INVALID", str(exc)) from exc

    @staticmethod
    def _verify_statistics(expected_result: str, result: OnlyResearchStatisticsResult) -> None:
        manifest = result.manifest
        if manifest.plan.statistics_fingerprint != manifest.statistics_fingerprint:
            raise ValueError("Statistics Plan identity mismatch")
        if any(not isinstance(row, OnlyResearchStatisticRow) for row in result.rows):
            raise ValueError("Statistics row contract is invalid")
        timestamps = tuple(row.ts_event_ns for row in result.rows)
        if timestamps != tuple(sorted(timestamps)) or len(timestamps) != len(set(timestamps)):
            raise ValueError("Statistics rows are not canonical")
        content = only_research_statistics_result_content_fingerprint(
            tuple(row.semantic_payload() for row in result.rows)
        )
        if content != manifest.result_content_fingerprint:
            raise ValueError("Statistics content identity mismatch")
        identity = only_research_statistics_result_fingerprint(manifest.statistics_fingerprint, content)
        if identity != manifest.statistics_result_fingerprint or identity != expected_result:
            raise ValueError("Statistics Result identity mismatch")
        if len(result.rows) != manifest.row_count:
            raise ValueError("Statistics row count mismatch")
