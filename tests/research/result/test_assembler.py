from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from onlyalpha.research import OnlyResearchResultAssembler, OnlyResearchResultError, OnlyResearchResultPlan
from tests.research.evaluation.support import statistics_case
from tests.research.result.support import result_case


class _MappingStatisticsStore:
    def __init__(self, values):  # type: ignore[no-untyped-def]
        self.values = values

    def load_verified(self, statistics_fingerprint: str):  # type: ignore[no-untyped-def]
        return self.values[statistics_fingerprint]


def test_assembler_loads_verified_authorities_and_enforces_canonical_references(tmp_path) -> None:
    plan, assembler, _, result, _ = result_case(tmp_path)
    second = assembler.assemble(OnlyResearchResultPlan(tuple(reversed(plan.statistics_fingerprints))))

    assert result.manifest.statistics_results == tuple(sorted(result.manifest.statistics_results))
    assert result.manifest == second.manifest
    assert result.manifest.research_result_plan_fingerprint == plan.fingerprint
    assert type(result.manifest).from_dict(result.manifest.to_dict()) == result.manifest


def test_assembler_rejects_cross_dataset_composition(tmp_path) -> None:
    first = statistics_case(tmp_path / "first")
    second = statistics_case(tmp_path / "second")
    first_result = first[8].load_verified(first[6].statistics_fingerprint)
    second_result = second[8].load_verified(second[6].statistics_fingerprint)
    second_identity = "f" * 64
    second_manifest = SimpleNamespace(
        statistics_fingerprint=second_identity,
        statistics_result_fingerprint=second_result.manifest.statistics_result_fingerprint,
        dataset_snapshot_fingerprint="e" * 64,
    )
    store = _MappingStatisticsStore(
        {
            first[6].statistics_fingerprint: first_result,
            second_identity: SimpleNamespace(manifest=second_manifest),
        }
    )
    assembler = OnlyResearchResultAssembler(store, audit_time=lambda: datetime(2026, 8, 15, tzinfo=UTC))

    with pytest.raises(OnlyResearchResultError) as raised:
        assembler.assemble(OnlyResearchResultPlan((first[6].statistics_fingerprint, second_identity)))
    assert raised.value.code == "RESEARCH_RESULT_INVALID"
    assert "one exact Dataset Snapshot" in raised.value.detail


def test_execution_disposition_and_physical_location_do_not_enter_identity(tmp_path) -> None:
    plan1, assembler1, _, result1, _ = result_case(tmp_path / "one")
    plan2, assembler2, _, result2, _ = result_case(tmp_path / "two")

    assert plan1 == plan2
    assert (
        assembler1.assemble(plan1).manifest.research_result_fingerprint == result1.manifest.research_result_fingerprint
    )
    assert (
        assembler2.assemble(plan2).manifest.research_result_fingerprint == result2.manifest.research_result_fingerprint
    )
    assert result1.manifest.research_result_fingerprint == result2.manifest.research_result_fingerprint


def test_assembler_rejects_invalid_plan_and_upstream_logical_identity(tmp_path) -> None:
    with pytest.raises(OnlyResearchResultError) as invalid_plan:
        OnlyResearchResultAssembler({}, audit_time=lambda: datetime(2026, 8, 16, tzinfo=UTC)).assemble(None)  # type: ignore[arg-type]
    assert invalid_plan.value.code == "RESEARCH_RESULT_INVALID"

    plan, _, _, result, _ = result_case(tmp_path)
    first = result.manifest.statistics_results[0]
    mismatched = SimpleNamespace(
        manifest=SimpleNamespace(
            statistics_fingerprint="e" * 64,
            statistics_result_fingerprint=first.statistics_result_fingerprint,
            dataset_snapshot_fingerprint=result.manifest.dataset_snapshot_fingerprint,
        )
    )
    assembler = OnlyResearchResultAssembler(
        _MappingStatisticsStore({first.statistics_fingerprint: mismatched}),
        audit_time=lambda: datetime(2026, 8, 16, tzinfo=UTC),
    )
    one_member_plan = OnlyResearchResultPlan((first.statistics_fingerprint,))

    with pytest.raises(OnlyResearchResultError) as logical_mismatch:
        assembler.assemble(one_member_plan)
    assert logical_mismatch.value.code == "RESEARCH_RESULT_INVALID"
    assert "logical identity" in logical_mismatch.value.detail


@pytest.mark.parametrize(
    "audit_time",
    (
        lambda: "2026-08-16T00:00:00Z",
        lambda: datetime(2026, 8, 16),
        lambda: datetime(2026, 8, 16, tzinfo=timezone(timedelta(hours=8))),
    ),
)
def test_assembler_rejects_non_utc_audit_evidence(tmp_path, audit_time) -> None:  # type: ignore[no-untyped-def]
    plan, _, _, _, statistics_store = result_case(tmp_path)
    assembler = OnlyResearchResultAssembler(statistics_store, audit_time=audit_time)

    with pytest.raises(OnlyResearchResultError) as raised:
        assembler.assemble(plan)
    assert raised.value.code == "RESEARCH_RESULT_INVALID"
    assert "timezone-aware UTC" in raised.value.detail
