from datetime import date, time
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyMarginMode, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.trading import (
    OnlyCloseScope,
    OnlyExposureConstraint,
    OnlyPositionEffect,
    OnlyPositionMode,
)
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.economics import (
    OnlyCompiledFundingPolicy,
    OnlyCompiledMarginPolicy,
    OnlyCompiledOrderCapabilityPolicy,
    OnlyCompiledValuationPolicy,
    OnlyEconomicModel,
    OnlyMarginIsolationScope,
    OnlyMarginRequirementTier,
    OnlyReferencePriceKind,
)
from onlyalpha.market.models import (
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
    OnlyMarketPositionMode,
    OnlyPositionAccountingModel,
    OnlyPriceBandRoundingMode,
    OnlySettlementModel,
    OnlySettlementRule,
    OnlySettlementTiming,
    OnlyShortSellingMode,
    OnlyShortSellingRule,
    OnlyTradingPhase,
    OnlyTradingSessionDefinition,
    OnlyTradingSessionModel,
)
from onlyalpha.market.product import (
    OnlyCompiledInstrumentMarketTerms,
    OnlyCompiledMarketPolicy,
    OnlyInstrumentTradingStatus,
    OnlyMarketProductAuthorityIdentity,
)


def _futures_policy(*, initial_rate: Decimal = Decimal("0.10")) -> OnlyCompiledMarketPolicy:
    compiler = OnlyMarketProductAuthorityIdentity(
        "POLICY_COMPILER", "synthetic-futures", "1", only_identity_fingerprint(("synthetic-futures", "1"))
    )
    immediate = OnlySettlementRule(OnlySettlementTiming.IMMEDIATE)
    return OnlyCompiledMarketPolicy.create(
        instrument_id=OnlyInstrumentId.parse("TEST.FUT"),
        trading_day=OnlyTradingDay(date(2026, 9, 1)),
        reference_fingerprint=only_identity_fingerprint(("TEST.FUT", "reference")),
        compiler=compiler,
        instrument_terms=OnlyCompiledInstrumentMarketTerms("USD", Decimal("10"), OnlyInstrumentTradingStatus.TRADABLE),
        session_policy=OnlyTradingSessionModel(
            "TEST", "UTC", (OnlyTradingSessionDefinition("all", time(0), time(0), OnlyTradingPhase.CONTINUOUS),)
        ),
        price_policy=OnlyCompiledPriceBandPolicy(
            "TEST", Decimal("0.01"), None, None, None, None, OnlyPriceBandRoundingMode.HALF_UP_TO_TICK
        ),
        quantity_policy=OnlyCompiledQuantityPolicy(
            Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), False, None, False
        ),
        position_policy=OnlyPositionAccountingModel(OnlyMarketPositionMode.NETTING),
        short_policy=OnlyShortSellingRule(OnlyShortSellingMode.ENABLED_UNRESTRICTED),
        settlement_policy=OnlySettlementModel("FUTURES", immediate, immediate, immediate, immediate),
        margin_policy=None,
        economic_model=OnlyEconomicModel.MARGINED_DERIVATIVE,
        order_capability_policy=OnlyCompiledOrderCapabilityPolicy(
            (OnlyOrderType.LIMIT,),
            (OnlyTimeInForce.GTC,),
            (OnlyPositionEffect.OPEN, OnlyPositionEffect.CLOSE),
            (OnlyCloseScope.ANY,),
            (OnlyExposureConstraint.NONE, OnlyExposureConstraint.REDUCE_ONLY),
            (OnlyPositionMode.NETTING, OnlyPositionMode.HEDGING),
        ),
        compiled_margin_policy=OnlyCompiledMarginPolicy(
            OnlyMarginMode.CROSS,
            "USD",
            OnlyMarginIsolationScope.ACCOUNT,
            OnlyReferencePriceKind.MARK,
            (
                OnlyMarginRequirementTier(Decimal("100000"), initial_rate, Decimal("0.05")),
                OnlyMarginRequirementTier(None, Decimal("0.20"), Decimal("0.10")),
            ),
        ),
        valuation_policy=OnlyCompiledValuationPolicy(OnlyReferencePriceKind.MARK, OnlyReferencePriceKind.MARK),
        funding_policy=OnlyCompiledFundingPolicy(8 * 60 * 60, OnlyReferencePriceKind.MARK),
    )


def test_tiered_margin_requirement_and_policy_identity_are_deterministic() -> None:
    policy = _futures_policy()
    assert policy.policy_schema_version == 2
    assert policy.compiled_margin_policy is not None
    assert policy.compiled_margin_policy.requirement(Decimal("50000")) == (
        Decimal("5000.00"),
        Decimal("2500.00"),
    )
    assert policy.compiled_margin_policy.requirement(Decimal("150000")) == (
        Decimal("30000.00"),
        Decimal("15000.00"),
    )
    assert _futures_policy().identity.policy_fingerprint == policy.identity.policy_fingerprint
    assert (
        _futures_policy(initial_rate=Decimal("0.12")).identity.policy_fingerprint != policy.identity.policy_fingerprint
    )


def test_invalid_margin_scope_and_cash_derivative_policy_fail_closed() -> None:
    with pytest.raises(ValueError, match="CROSS_MARGIN_SCOPE"):
        OnlyCompiledMarginPolicy(
            OnlyMarginMode.CROSS,
            "USD",
            OnlyMarginIsolationScope.POSITION_LEG,
            OnlyReferencePriceKind.MARK,
            (OnlyMarginRequirementTier(None, Decimal("0.1"), Decimal("0.05")),),
        )
