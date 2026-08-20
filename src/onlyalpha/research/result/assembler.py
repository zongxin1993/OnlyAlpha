"""Research Result composition from verified Statistics authorities."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.evaluation.result import OnlyResearchStatisticsResult

from .errors import OnlyResearchResultError
from .identity import (
    RESEARCH_RESULT_SCIENTIFIC_SCHEMA_VERSION,
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)
from .plan import OnlyResearchResultPlan
from .result import (
    OnlyResearchCalculationResultReference,
    OnlyResearchResult,
    OnlyResearchResultManifest,
    OnlyResearchStatisticsResultReference,
)


class _StatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchStatisticsResult: ...


class _CalculationResultStore(Protocol):
    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult: ...


class OnlyResearchResultAssembler:
    def __init__(
        self,
        statistics_result_store: _StatisticsResultStore,
        *,
        audit_time: Callable[[], datetime],
        calculation_result_store: _CalculationResultStore | None = None,
    ) -> None:
        self._statistics_result_store = statistics_result_store
        self._audit_time = audit_time
        self._calculation_result_store = calculation_result_store

    def assemble(self, plan: OnlyResearchResultPlan) -> OnlyResearchResult:
        if not isinstance(plan, OnlyResearchResultPlan):
            raise OnlyResearchResultError("RESEARCH_RESULT_INVALID", "Plan contract is invalid")
        references: list[OnlyResearchStatisticsResultReference] = []
        calculation_references: list[OnlyResearchCalculationResultReference] = []
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
            schema_version = plan.schema_version
            if schema_version == RESEARCH_RESULT_SCIENTIFIC_SCHEMA_VERSION:
                if self._calculation_result_store is None:
                    raise ValueError("Scientific Research Result requires Calculation Result Store")
                if dataset != plan.dataset_snapshot_fingerprint:
                    raise ValueError("Research Result Plan Dataset linkage mismatch")
                calculations = {}
                for member in plan.calculations:
                    calculation_upstream = self._calculation_result_store.load_verified(member.calculation_fingerprint)
                    calculation_manifest = calculation_upstream.manifest
                    if calculation_manifest.calculation_fingerprint != member.calculation_fingerprint:
                        raise ValueError("Calculation logical identity linkage mismatch")
                    if calculation_manifest.dataset_snapshot_fingerprint != plan.dataset_snapshot_fingerprint:
                        raise ValueError("Calculation Result Dataset linkage mismatch")
                    if calculation_manifest.calculation_graph_fingerprint != member.graph_fingerprint:
                        raise ValueError("Calculation Result Graph linkage mismatch")
                    calculations[member.calculation_fingerprint] = calculation_upstream
                    calculation_references.append(
                        OnlyResearchCalculationResultReference(
                            member.calculation_fingerprint, calculation_manifest.calculation_result_fingerprint
                        )
                    )
                self._verify_scientific_members(plan, calculations)
            created_at = self._audit_timestamp()
            canonical = tuple(sorted(references))
            canonical_calculations = tuple(sorted(calculation_references))
            content = only_research_result_content_fingerprint(
                tuple(item.to_dict() for item in canonical),
                tuple(item.to_dict() for item in canonical_calculations),
                schema_version=schema_version,
            )
            result = only_research_result_fingerprint(plan.fingerprint, content, schema_version=schema_version)
            assert dataset is not None
            return OnlyResearchResult(
                OnlyResearchResultManifest(
                    plan,
                    plan.fingerprint,
                    dataset,
                    canonical,
                    content,
                    result,
                    created_at,
                    schema_version,
                    canonical_calculations,
                )
            )
        except OnlyResearchResultError:
            raise
        except Exception as exc:
            raise OnlyResearchResultError("RESEARCH_RESULT_INVALID", str(exc)) from exc

    @staticmethod
    def _verify_scientific_members(
        plan: OnlyResearchResultPlan, calculations: dict[str, OnlyResearchCalculationResult]
    ) -> None:
        for member in plan.published_series:
            graph = calculations[member.calculation_fingerprint].manifest.calculation_graph
            node = next((item for item in graph.nodes if item.fingerprint == member.node_fingerprint), None)
            if node is None:
                raise ValueError("Scientific member node is absent from exact Graph")
            output = next((item for item in node.definition.outputs if item.name == member.output_name), None)
            if output is None:
                raise ValueError("Scientific member output is absent from exact Graph")
        for signal_member in plan.signals:
            graph = calculations[signal_member.calculation_fingerprint].manifest.calculation_graph
            node = next((item for item in graph.nodes if item.fingerprint == signal_member.node_fingerprint), None)
            if node is None:
                raise ValueError("Scientific member node is absent from exact Graph")
            output = next((item for item in node.definition.outputs if item.name == signal_member.output_name), None)
            if output is None or output.semantic_type != signal_member.role:
                raise ValueError("Scientific Signal role does not match exact Graph")

    def _audit_timestamp(self) -> datetime:
        value = self._audit_time()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise OnlyResearchResultError("RESEARCH_RESULT_INVALID", "audit time must be timezone-aware UTC")
        return value
