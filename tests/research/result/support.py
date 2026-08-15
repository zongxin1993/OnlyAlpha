from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyResearchResultAssembler,
    OnlyResearchResultPlan,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsMethod,
)
from tests.research.evaluation.support import statistics_case


def result_case(root: Path):
    case = statistics_case(root)
    statistics_plan = case[6]
    statistics_store = case[8]
    statistics_executor = case[9]
    second_plan = replace(
        statistics_plan,
        definition=OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.RANK_IC),
    )
    statistics_executor.execute(second_plan)
    plan = OnlyResearchResultPlan((second_plan.statistics_fingerprint, statistics_plan.statistics_fingerprint))
    assembler = OnlyResearchResultAssembler(
        statistics_store,
        audit_time=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )
    store = OnlyJsonResearchResultStore(root / "research-results", statistics_store)
    return plan, assembler, store, assembler.assemble(plan), statistics_store
