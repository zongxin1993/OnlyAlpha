from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.strategy import (
    OnlyInMemoryStrategyPromotionLedger,
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionError,
    OnlyStrategyPromotionService,
    OnlyStrategyPromotionStage,
    OnlyStrategyRevisionStore,
)
from tests.strategy.p9_support import p9_strategy_case


def test_promotion_is_append_only_chained_evidence_with_derived_stage(tmp_path) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")
    store.commit(revision)
    ledger = OnlyInMemoryStrategyPromotionLedger()
    times = iter(
        (
            datetime(2026, 8, 24, tzinfo=UTC),
            datetime(2026, 8, 24, tzinfo=UTC) + timedelta(seconds=1),
            datetime(2026, 8, 24, tzinfo=UTC) + timedelta(seconds=2),
        )
    )
    service = OnlyStrategyPromotionService(store, ledger, lambda: next(times))
    fingerprint = str(revision.strategy_fingerprint)

    first = service.record(
        strategy_fingerprint=fingerprint,
        to_stage=OnlyStrategyPromotionStage.BACKTEST,
        evidence_fingerprints=("a" * 64,),
        decision=OnlyStrategyPromotionDecision.APPROVED,
        reason="exact historical evidence accepted",
        actor="operator",
    )
    second = service.record(
        strategy_fingerprint=fingerprint,
        to_stage=OnlyStrategyPromotionStage.SIM,
        evidence_fingerprints=("b" * 64,),
        decision=OnlyStrategyPromotionDecision.APPROVED,
        reason="realtime simulation evidence accepted",
        actor="operator",
    )
    third = service.record(
        strategy_fingerprint=fingerprint,
        to_stage=OnlyStrategyPromotionStage.LIVE_ELIGIBLE,
        evidence_fingerprints=("c" * 64,),
        decision=OnlyStrategyPromotionDecision.REJECTED,
        reason="eligibility evidence rejected",
        actor="operator",
    )

    assert first.previous_record_fingerprint is None
    assert second.previous_record_fingerprint == first.record_fingerprint
    assert third.previous_record_fingerprint == second.record_fingerprint
    assert service.current_stage(fingerprint) is OnlyStrategyPromotionStage.SIM
    assert ledger.records(fingerprint) == (first, second, third)


@pytest.mark.parametrize(
    "target",
    (OnlyStrategyPromotionStage.SIM, OnlyStrategyPromotionStage.LIVE_ELIGIBLE),
)
def test_promotion_rejects_stage_skips(tmp_path, target) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")
    store.commit(revision)
    service = OnlyStrategyPromotionService(
        store,
        OnlyInMemoryStrategyPromotionLedger(),
        lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )

    with pytest.raises(OnlyStrategyPromotionError) as error:
        service.record(
            strategy_fingerprint=str(revision.strategy_fingerprint),
            to_stage=target,
            evidence_fingerprints=("a" * 64,),
            decision=OnlyStrategyPromotionDecision.APPROVED,
            reason="illegal skip",
            actor="operator",
        )
    assert error.value.code == "ILLEGAL_PROMOTION_TRANSITION"


def test_promotion_rejects_unknown_strategy(tmp_path) -> None:
    service = OnlyStrategyPromotionService(
        OnlyStrategyRevisionStore(tmp_path / "semantic"),
        OnlyInMemoryStrategyPromotionLedger(),
        lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )
    with pytest.raises(OnlyStrategyPromotionError) as error:
        service.current_stage("f" * 64)
    assert error.value.code == "STRATEGY_NOT_FOUND"


def test_promotion_records_are_immutable_and_invalid_evidence_fails_closed(tmp_path) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")
    store.commit(revision)
    service = OnlyStrategyPromotionService(
        store,
        OnlyInMemoryStrategyPromotionLedger(),
        lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )
    with pytest.raises(OnlyStrategyPromotionError) as error:
        service.record(
            strategy_fingerprint=str(revision.strategy_fingerprint),
            to_stage=OnlyStrategyPromotionStage.BACKTEST,
            evidence_fingerprints=("not-evidence",),
            decision=OnlyStrategyPromotionDecision.APPROVED,
            reason="invalid evidence",
            actor="operator",
        )
    assert error.value.code == "PROMOTION_RECORD_INVALID"

    record = service.record(
        strategy_fingerprint=str(revision.strategy_fingerprint),
        to_stage=OnlyStrategyPromotionStage.BACKTEST,
        evidence_fingerprints=("a" * 64,),
        decision=OnlyStrategyPromotionDecision.APPROVED,
        reason="valid evidence",
        actor="operator",
    )
    with pytest.raises(FrozenInstanceError):
        record.reason = "mutated"  # type: ignore[misc]
