from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.application import OnlyEconomicBaseline
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.operations.acceptance import (
    OnlyAcceptanceEvidence,
    OnlyAcceptanceVerdict,
    OnlyPaperAcceptanceAssertions,
    OnlyPaperAcceptancePlan,
)

pytestmark = pytest.mark.unit


def test_economic_isolation_detects_cash_mutation() -> None:
    baseline = OnlyEconomicBaseline(Decimal("100"), 0, Decimal(0), 0, 0, 0, 0, 0, 0, 0)
    passed, reason, _, _ = OnlyPaperAcceptanceAssertions().economic_isolation(
        baseline, replace(baseline, cash_balance=Decimal("99"))
    )
    assert not passed
    assert reason == "ECONOMIC_STATE_MUTATED"


def test_evidence_rejects_absolute_or_parent_artifact_paths() -> None:
    stamp = OnlyTimestamp.from_datetime(datetime(2026, 8, 3, tzinfo=UTC))
    with pytest.raises(ValueError, match="relative"):
        OnlyAcceptanceEvidence(
            "evidence",
            "case",
            "category",
            OnlyAcceptanceVerdict.FAIL,
            "reason",
            stamp,
            stamp,
            artifact_paths=("../secret",),
        )


def test_explicit_output_override_is_relative_to_working_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    plan = OnlyPaperAcceptancePlan.load(
        Path(__file__).resolve().parents[2] / "examples/acceptance/miniqmt_paper_v2.yaml",
        output_override=Path("user_data/acceptance/paper"),
    )
    assert plan.output_root == tmp_path / "user_data/acceptance/paper"
