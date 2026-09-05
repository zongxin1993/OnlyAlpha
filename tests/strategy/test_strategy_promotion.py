from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.strategy import (
    OnlyFrozenStrategyRevisionStore,
    OnlyStrategyPromotionError,
)
from onlyalpha.strategy.promotion import (
    OnlyInMemoryStrategyPromotionLedger,
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionRecord,
    OnlyStrategyPromotionService,
    OnlyStrategyPromotionStage,
    _only_authorize_qualified_promotion,
    only_verified_strategy_promotion_chain,
)
from tests.strategy.p9_support import p9_strategy_case, publish_frozen_strategy_for_execution_test


def test_promotion_is_append_only_chained_evidence_with_derived_stage(tmp_path) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", revision)
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
        qualification_authorization=_only_authorize_qualified_promotion("a" * 64),
    )
    second = service.record(
        strategy_fingerprint=fingerprint,
        to_stage=OnlyStrategyPromotionStage.SIM,
        evidence_fingerprints=("b" * 64,),
        decision=OnlyStrategyPromotionDecision.APPROVED,
        reason="realtime simulation evidence accepted",
        actor="operator",
        qualification_authorization=_only_authorize_qualified_promotion("b" * 64),
    )
    third = service.record(
        strategy_fingerprint=fingerprint,
        to_stage=OnlyStrategyPromotionStage.LIVE_ELIGIBLE,
        evidence_fingerprints=("c" * 64,),
        decision=OnlyStrategyPromotionDecision.REJECTED,
        reason="eligibility evidence rejected",
        actor="operator",
        qualification_authorization=_only_authorize_qualified_promotion("c" * 64),
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
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", revision)
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
            qualification_authorization=_only_authorize_qualified_promotion("a" * 64),
        )
    assert error.value.code == "ILLEGAL_PROMOTION_TRANSITION"


def test_promotion_rejects_unknown_strategy(tmp_path) -> None:
    service = OnlyStrategyPromotionService(
        OnlyFrozenStrategyRevisionStore(tmp_path / "semantic"),
        OnlyInMemoryStrategyPromotionLedger(),
        lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )
    with pytest.raises(OnlyStrategyPromotionError) as error:
        service.current_stage("f" * 64)
    assert error.value.code == "STRATEGY_NOT_FOUND"


def test_promotion_records_are_immutable_and_invalid_evidence_fails_closed(tmp_path) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", revision)
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
            qualification_authorization=_only_authorize_qualified_promotion("a" * 64),
        )
    assert error.value.code == "PROMOTION_RECORD_INVALID"

    record = service.record(
        strategy_fingerprint=str(revision.strategy_fingerprint),
        to_stage=OnlyStrategyPromotionStage.BACKTEST,
        evidence_fingerprints=("a" * 64,),
        decision=OnlyStrategyPromotionDecision.APPROVED,
        reason="valid evidence",
        actor="operator",
        qualification_authorization=_only_authorize_qualified_promotion("a" * 64),
    )
    with pytest.raises(FrozenInstanceError):
        record.reason = "mutated"  # type: ignore[misc]


def test_promotion_chain_order_is_timestamp_independent(tmp_path) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", revision)
    ledger = OnlyInMemoryStrategyPromotionLedger()
    timestamps = iter(
        (
            datetime(2026, 8, 24, 0, 0, 2, tzinfo=UTC),
            datetime(2026, 8, 24, 0, 0, 1, tzinfo=UTC),
            datetime(2026, 8, 24, 0, 0, 1, tzinfo=UTC),
        )
    )
    service = OnlyStrategyPromotionService(store, ledger, lambda: next(timestamps))
    fingerprint = str(revision.strategy_fingerprint)
    for stage, evidence in (
        (OnlyStrategyPromotionStage.BACKTEST, "a" * 64),
        (OnlyStrategyPromotionStage.SIM, "b" * 64),
        (OnlyStrategyPromotionStage.LIVE_ELIGIBLE, "c" * 64),
    ):
        service.record(
            strategy_fingerprint=fingerprint,
            to_stage=stage,
            evidence_fingerprints=(evidence,),
            decision=OnlyStrategyPromotionDecision.APPROVED,
            reason="exact evidence",
            actor="operator",
            qualification_authorization=_only_authorize_qualified_promotion(evidence),
        )

    assert service.current_stage(fingerprint) is OnlyStrategyPromotionStage.LIVE_ELIGIBLE
    assert only_verified_strategy_promotion_chain(
        tuple(reversed(ledger.records(fingerprint))),
        fingerprint,
    ) == ledger.records(fingerprint)


def test_promotion_recording_requires_verified_qualification_authorization(tmp_path) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    store = OnlyFrozenStrategyRevisionStore(tmp_path / "semantic")
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", revision)
    service = OnlyStrategyPromotionService(
        store,
        OnlyInMemoryStrategyPromotionLedger(),
        lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )
    with pytest.raises(OnlyStrategyPromotionError) as error:
        service.record(
            strategy_fingerprint=str(revision.strategy_fingerprint),
            to_stage=OnlyStrategyPromotionStage.BACKTEST,
            evidence_fingerprints=("a" * 64,),
            decision=OnlyStrategyPromotionDecision.APPROVED,
            reason="must not bypass evaluator proof",
            actor="operator",
            qualification_authorization=object(),  # type: ignore[arg-type]
        )
    assert error.value.code == "QUALIFICATION_DECISION_NOT_APPROVED"


def test_promotion_chain_rejects_two_heads_branch_and_orphan() -> None:
    fingerprint = "a" * 64
    now = datetime(2026, 8, 24, tzinfo=UTC)
    first = OnlyStrategyPromotionRecord(
        fingerprint,
        OnlyStrategyPromotionStage.RESEARCH,
        OnlyStrategyPromotionStage.BACKTEST,
        ("b" * 64,),
        OnlyStrategyPromotionDecision.APPROVED,
        "first",
        "operator",
        now,
    )
    second_head = OnlyStrategyPromotionRecord(
        fingerprint,
        OnlyStrategyPromotionStage.RESEARCH,
        OnlyStrategyPromotionStage.BACKTEST,
        ("c" * 64,),
        OnlyStrategyPromotionDecision.APPROVED,
        "second head",
        "operator",
        now,
    )
    with pytest.raises(OnlyStrategyPromotionError, match="one head"):
        only_verified_strategy_promotion_chain((first, second_head), fingerprint)

    child = OnlyStrategyPromotionRecord(
        fingerprint,
        OnlyStrategyPromotionStage.BACKTEST,
        OnlyStrategyPromotionStage.SIM,
        ("d" * 64,),
        OnlyStrategyPromotionDecision.APPROVED,
        "child",
        "operator",
        now,
        first.record_fingerprint,
    )
    branch = OnlyStrategyPromotionRecord(
        fingerprint,
        OnlyStrategyPromotionStage.BACKTEST,
        OnlyStrategyPromotionStage.SIM,
        ("e" * 64,),
        OnlyStrategyPromotionDecision.APPROVED,
        "branch",
        "operator",
        now,
        first.record_fingerprint,
    )
    with pytest.raises(OnlyStrategyPromotionError, match="branches"):
        only_verified_strategy_promotion_chain((first, child, branch), fingerprint)

    orphan = OnlyStrategyPromotionRecord(
        fingerprint,
        OnlyStrategyPromotionStage.BACKTEST,
        OnlyStrategyPromotionStage.SIM,
        ("f" * 64,),
        OnlyStrategyPromotionDecision.APPROVED,
        "orphan",
        "operator",
        now,
        "9" * 64,
    )
    with pytest.raises(OnlyStrategyPromotionError, match="orphan"):
        only_verified_strategy_promotion_chain((first, orphan), fingerprint)
