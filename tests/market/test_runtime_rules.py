from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.enums import OnlyAssetClass, OnlyOrderSide, OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.models import OnlyInstrumentReferenceSnapshot, OnlyMarketProfileId
from onlyalpha.market.profiles import only_builtin_market_profile_registry
from onlyalpha.market.registry import OnlyMarketProfileRequest
from onlyalpha.market.runtime_rules import (
    OnlyMarketRuleCompiler,
    OnlyMarketRuleEngine,
    OnlyPreTradeMarketContext,
    OnlyTradeApplicationRequest,
    only_ashare_instrument_reference,
)


def _engine(profile: OnlyMarketProfileId, reference_registry_fingerprint: str | None = None) -> OnlyMarketRuleEngine:
    reference = OnlyInstrumentReferenceSnapshot(
        "TEST.VENUE",
        OnlyAssetClass.EQUITY,
        "VENUE",
        profile,
        "USD",
        datetime(2020, 1, 1, tzinfo=UTC),
        None,
        "test",
        "1",
        "reference-fingerprint",
        quantity_step=Decimal(1),
    )
    return OnlyMarketRuleEngine(
        registry=only_builtin_market_profile_registry(),
        compiler=OnlyMarketRuleCompiler(),
        request=OnlyMarketProfileRequest(profile),
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        references={"TEST.VENUE": reference},
        advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
        reference_registry_fingerprint=reference_registry_fingerprint,
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


def test_checkpoint_restore_validates_reference_registry_fingerprint() -> None:
    original = _engine(OnlyMarketProfileId.GENERIC_T0_CASH, "registry-a")
    payload = original.capture_checkpoint()
    _engine(OnlyMarketProfileId.GENERIC_T0_CASH, "registry-a").restore_checkpoint(payload)
    with pytest.raises(ValueError, match="REFERENCE_FINGERPRINT_MISMATCH"):
        _engine(OnlyMarketProfileId.GENERIC_T0_CASH, "registry-b").restore_checkpoint(payload)


def test_a_share_rule_engine_consumes_resolved_record_and_uses_official_previous_close() -> None:
    config = OnlyClusterRunConfig.load("examples/configs/tushare_daily_backtest.yaml")
    registry = config.reference_data.ashare_registry
    instruments = config.reference_data.instrument_by_id

    def provider(instrument_id: str, trading_day: OnlyTradingDay) -> OnlyInstrumentReferenceSnapshot:
        identity = OnlyInstrumentId.parse(instrument_id)
        return only_ashare_instrument_reference(
            instruments[identity],
            registry.resolve(identity, trading_day).require_snapshot(),
            profile_id=OnlyMarketProfileId.CN_A_SHARE_CASH,
        )

    engine = OnlyMarketRuleEngine(
        registry=only_builtin_market_profile_registry(),
        compiler=OnlyMarketRuleCompiler(),
        request=OnlyMarketProfileRequest(OnlyMarketProfileId.CN_A_SHARE_CASH),
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        references=provider,
        advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
        reference_registry_fingerprint=registry.fingerprint,
    )
    day = OnlyTradingDay(date(2025, 1, 2))
    compiled = engine.compiled_rules("600000.XSHG", day)
    assert compiled.identity.reference_fingerprint == registry.records[0].record_fingerprint
    decision = engine.evaluate_pre_trade(
        OnlyPreTradeMarketContext(
            "600000.XSHG",
            OnlyOrderSide.BUY,
            Decimal("100"),
            Decimal("10.00"),
            datetime(2025, 1, 2, 2, tzinfo=UTC),
            day,
            available_cash=Decimal("100000"),
            previous_close=Decimal("9.99"),
        )
    )
    assert not decision.accepted
    assert decision.reason_code == "REFERENCE_ADJUSTMENT_SEMANTICS_CONFLICT"
