from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from onlyalpha.domain.enums import OnlyAssetClass, OnlyOrderSide, OnlyRuntimeMode
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.models import (
    OnlyInstrumentReferenceSnapshot,
    OnlyMarketProfileId,
    OnlyMarketRuleEvaluationStatus,
)
from onlyalpha.market.profiles import only_builtin_market_profile_registry
from onlyalpha.market.registry import OnlyMarketProfileRequest
from onlyalpha.market.runtime_rules import (
    OnlyMarketRuleCompiler,
    OnlyMarketRuleEngine,
    OnlyPreTradeMarketContext,
    OnlyTradeApplicationRequest,
)


def _reference(
    profile: OnlyMarketProfileId,
    *,
    board: str | None = None,
    st_status: bool = False,
    suspended: bool = False,
    status: str = "ACTIVE",
    previous_close: Decimal | None = None,
    tick_size: Decimal = Decimal("0.01"),
    lot_size: Decimal | None = None,
    fingerprint: str = "reference-fingerprint",
) -> OnlyInstrumentReferenceSnapshot:
    return OnlyInstrumentReferenceSnapshot(
        "TEST.XSHG" if profile is OnlyMarketProfileId.CN_A_SHARE_CASH else "TEST.VENUE",
        OnlyAssetClass.EQUITY,
        "XSHG" if profile is OnlyMarketProfileId.CN_A_SHARE_CASH else "VENUE",
        profile,
        "CNY" if profile is OnlyMarketProfileId.CN_A_SHARE_CASH else "USD",
        datetime(2020, 1, 1, tzinfo=UTC),
        None,
        "test",
        "1",
        fingerprint,
        status=status,
        tick_size=tick_size,
        quantity_step=Decimal(1),
        lot_size=lot_size,
        board=board,
        st_status=st_status,
        suspended=suspended,
        previous_close=previous_close,
    )


def _engine(
    profile: OnlyMarketProfileId,
    *,
    reference: OnlyInstrumentReferenceSnapshot | None = None,
    reference_registry_fingerprint: str | None = None,
) -> OnlyMarketRuleEngine:
    selected = reference or _reference(profile)
    return OnlyMarketRuleEngine(
        registry=only_builtin_market_profile_registry(),
        compiler=OnlyMarketRuleCompiler(),
        request=OnlyMarketProfileRequest(profile),
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        references={selected.instrument_id: selected},
        advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
        reference_registry_fingerprint=reference_registry_fingerprint,
    )


def _ashare_engine(
    *,
    board: str = "SSE_MAIN",
    st_status: bool = False,
    suspended: bool = False,
    status: str = "ACTIVE",
    previous_close: Decimal = Decimal("10.00"),
    tick_size: Decimal = Decimal("0.01"),
    lot_size: Decimal = Decimal(100),
    fingerprint: str = "ashare-reference",
    registry_fingerprint: str = "registry",
) -> OnlyMarketRuleEngine:
    return _engine(
        OnlyMarketProfileId.CN_A_SHARE_CASH,
        reference=_reference(
            OnlyMarketProfileId.CN_A_SHARE_CASH,
            board=board,
            st_status=st_status,
            suspended=suspended,
            status=status,
            previous_close=previous_close,
            tick_size=tick_size,
            lot_size=lot_size,
            fingerprint=fingerprint,
        ),
        reference_registry_fingerprint=registry_fingerprint,
    )


def _local_utc(day: date, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(
        UTC
    )


def _decision(
    engine: OnlyMarketRuleEngine,
    day: date,
    *,
    side: OnlyOrderSide = OnlyOrderSide.BUY,
    quantity: Decimal = Decimal(100),
    price: Decimal = Decimal("10.00"),
    hour: int = 9,
    minute: int = 30,
    sellable: Decimal = Decimal(0),
):
    return engine.evaluate_pre_trade(
        OnlyPreTradeMarketContext(
            "TEST.XSHG",
            side,
            quantity,
            price,
            _local_utc(day, hour, minute),
            OnlyTradingDay(day),
            unreserved_sellable_quantity=sellable,
            available_cash=Decimal("100000"),
        )
    )


def test_compiled_rules_are_deterministic_and_profile_does_not_escape() -> None:
    engine = _engine(OnlyMarketProfileId.GENERIC_T0_CASH)
    day = OnlyTradingDay(date(2026, 7, 17))
    first = engine.compiled_rules("TEST.VENUE", day)
    second = engine.compiled_rules("TEST.VENUE", day)
    assert first is second
    assert first.identity.compiled_rules_fingerprint == second.identity.compiled_rules_fingerprint
    assert not hasattr(first, "profile")


def test_pre_trade_and_trade_instruction_share_compiled_identity() -> None:
    engine = _engine(OnlyMarketProfileId.GENERIC_T0_CASH)
    day = OnlyTradingDay(date(2026, 7, 17))
    decision = engine.evaluate_pre_trade(
        OnlyPreTradeMarketContext(
            "TEST.VENUE",
            OnlyOrderSide.BUY,
            Decimal(2),
            Decimal(10),
            datetime(2026, 7, 17, 10, tzinfo=UTC),
            day,
            available_cash=Decimal(100),
        )
    )
    instruction = engine.build_trade_instruction(
        OnlyTradeApplicationRequest(
            "TEST.VENUE",
            "order-1",
            "trade-1",
            "account-1",
            OnlyOrderSide.BUY,
            Decimal(2),
            Decimal(10),
            datetime(2026, 7, 17, 10, tzinfo=UTC),
            day,
        )
    )
    assert decision.accepted
    assert decision.compiled_identity == instruction.compiled_identity
    assert instruction.settlement_instruction.asset_available_on == day


@pytest.mark.parametrize(
    ("trading_day", "expected_version", "expected_rate"),
    ((date(2026, 7, 5), "2025.1", Decimal("0.05")), (date(2026, 7, 6), "2026.07", Decimal("0.10"))),
)
def test_main_board_risk_warning_regime_switches_by_trading_day(
    trading_day: date, expected_version: str, expected_rate: Decimal
) -> None:
    decision = _decision(_ashare_engine(st_status=True), trading_day)
    assert decision.accepted
    assert decision.compiled_identity.profile_version == expected_version
    assert decision.daily_limit_rate == expected_rate


@pytest.mark.parametrize(
    ("board", "st_status", "expected_rate"),
    (
        ("SSE_MAIN", False, Decimal("0.10")),
        ("SZSE_MAIN", True, Decimal("0.05")),
        ("CHINEXT", False, Decimal("0.20")),
        ("CHINEXT", True, Decimal("0.20")),
        ("STAR", False, Decimal("0.20")),
        ("STAR", True, Decimal("0.20")),
    ),
)
def test_board_and_risk_warning_matrix_is_compiled(board: str, st_status: bool, expected_rate: Decimal) -> None:
    decision = _decision(_ashare_engine(board=board, st_status=st_status), date(2026, 7, 5))
    assert decision.daily_limit_rate == expected_rate


def test_price_band_is_tick_rounded_and_failures_are_precise() -> None:
    engine = _ashare_engine(previous_close=Decimal("10.03"))
    at_upper = _decision(engine, date(2026, 7, 5), price=Decimal("11.03"))
    above = _decision(engine, date(2026, 7, 5), price=Decimal("11.04"))
    below = _decision(engine, date(2026, 7, 5), price=Decimal("9.02"))
    unaligned = _decision(engine, date(2026, 7, 5), price=Decimal("10.001"))
    assert at_upper.accepted and at_upper.upper_limit == Decimal("11.03")
    assert above.reason_code == "PRICE_ABOVE_DAILY_LIMIT"
    assert below.reason_code == "PRICE_BELOW_DAILY_LIMIT"
    assert unaligned.reason_code == "PRICE_NOT_ALIGNED_TO_TICK"


@pytest.mark.parametrize(
    ("hour", "minute", "expected_phase", "expected_reason"),
    (
        (9, 14, "CLOSED", "MARKET_CLOSED"),
        (9, 15, "OPENING_AUCTION", "TRADING_PHASE_NOT_SUPPORTED"),
        (9, 30, "CONTINUOUS", None),
        (11, 30, "MIDDAY_BREAK", "MIDDAY_BREAK"),
        (13, 0, "CONTINUOUS", None),
        (14, 57, "CLOSING_AUCTION", "TRADING_PHASE_NOT_SUPPORTED"),
        (15, 0, "CLOSED", "MARKET_CLOSED"),
    ),
)
def test_ashare_session_phases_are_explicit(
    hour: int, minute: int, expected_phase: str, expected_reason: str | None
) -> None:
    decision = _decision(_ashare_engine(), date(2026, 7, 5), hour=hour, minute=minute)
    assert decision.trading_phase.value == expected_phase
    assert decision.reason_code == expected_reason


def test_suspension_and_inactive_reasons_are_distinct() -> None:
    assert _decision(_ashare_engine(suspended=True), date(2026, 7, 5)).reason_code == "INSTRUMENT_SUSPENDED"
    assert _decision(_ashare_engine(status="INACTIVE"), date(2026, 7, 5)).reason_code == "INSTRUMENT_INACTIVE"


@pytest.mark.parametrize(
    ("board", "quantity", "expected_reason"),
    (
        ("SSE_MAIN", Decimal(100), None),
        ("SSE_MAIN", Decimal(150), "BUY_QUANTITY_INCREMENT_INVALID"),
        ("CHINEXT", Decimal(100), None),
        ("CHINEXT", Decimal(150), "BUY_QUANTITY_INCREMENT_INVALID"),
        ("STAR", Decimal(199), "BUY_QUANTITY_BELOW_MINIMUM"),
        ("STAR", Decimal(200), None),
        ("STAR", Decimal(201), None),
    ),
)
def test_compiled_board_quantity_policies(board: str, quantity: Decimal, expected_reason: str | None) -> None:
    decision = _decision(_ashare_engine(board=board), date(2026, 7, 5), quantity=quantity)
    assert decision.reason_code == expected_reason


@pytest.mark.parametrize(
    ("quantity", "expected_reason"),
    (
        (Decimal(100), None),
        (Decimal(200), None),
        (Decimal(50), "ODD_LOT_SELL_REQUIRES_FULL_LIQUIDATION"),
        (Decimal(250), None),
    ),
)
def test_odd_lot_sell_requires_full_unreserved_liquidation(quantity: Decimal, expected_reason: str | None) -> None:
    decision = _decision(
        _ashare_engine(),
        date(2026, 7, 5),
        side=OnlyOrderSide.SELL,
        quantity=quantity,
        sellable=Decimal(250),
    )
    assert decision.reason_code == expected_reason


def test_first_failed_evaluation_is_stable_and_remaining_rules_are_not_evaluated() -> None:
    engine = _ashare_engine()
    payloads = []
    for _ in range(100):
        decision = _decision(
            engine,
            date(2026, 7, 5),
            quantity=Decimal(150),
            price=Decimal("11.01"),
            hour=11,
            minute=30,
        )
        payloads.append(decision)
    assert all(item == payloads[0] for item in payloads)
    assert payloads[0].reason_code == "MIDDAY_BREAK"
    assert payloads[0].evaluations[3].status is OnlyMarketRuleEvaluationStatus.FAILED
    assert all(item.status is OnlyMarketRuleEvaluationStatus.NOT_EVALUATED for item in payloads[0].evaluations[4:])


def test_checkpoint_round_trip_is_lossless_and_validates_authorities() -> None:
    original = _ashare_engine()
    expected = _decision(original, date(2026, 7, 5))
    payload = original.capture_checkpoint()
    restored = _ashare_engine()
    restored.restore_checkpoint(payload)
    assert restored.decisions == (expected,)
    with pytest.raises(ValueError, match="REFERENCE_FINGERPRINT_MISMATCH"):
        _ashare_engine(fingerprint="changed-reference").restore_checkpoint(payload)
    incompatible = dict(payload)
    incompatible["schema_version"] = 2
    with pytest.raises(ValueError, match="CHECKPOINT_SCHEMA_UNSUPPORTED"):
        _ashare_engine().restore_checkpoint(incompatible)


def test_missing_reference_returns_structured_fail_closed_decision() -> None:
    engine = OnlyMarketRuleEngine(
        registry=only_builtin_market_profile_registry(),
        compiler=OnlyMarketRuleCompiler(),
        request=OnlyMarketProfileRequest(OnlyMarketProfileId.CN_A_SHARE_CASH),
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        references={},
        advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
        reference_registry_fingerprint="empty-registry",
    )
    decision = engine.evaluate_pre_trade(
        OnlyPreTradeMarketContext(
            "MISSING.XSHG",
            OnlyOrderSide.BUY,
            Decimal(100),
            Decimal("10.00"),
            _local_utc(date(2026, 7, 5), 9, 30),
            OnlyTradingDay(date(2026, 7, 5)),
            available_cash=Decimal("100000"),
        )
    )
    assert decision.reason_code == "REFERENCE_NOT_FOUND"
    assert decision.evaluations[0].status is OnlyMarketRuleEvaluationStatus.FAILED
    assert all(item.status is OnlyMarketRuleEvaluationStatus.NOT_EVALUATED for item in decision.evaluations[1:])
