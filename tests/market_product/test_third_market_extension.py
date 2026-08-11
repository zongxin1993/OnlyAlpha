from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.fee.market_pack import OnlyMarketFeePack
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
    OnlyCanonicalMarketProductConfig,
    OnlyCompiledInstrumentMarketTerms,
    OnlyCompiledMarketPolicy,
    OnlyInstrumentTradingStatus,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductAuthorityIdentity,
    OnlyMarketProductCompositionIdentity,
    OnlyMarketProductConfig,
    OnlyMarketProductFactoryRegistry,
    OnlyMarketProductId,
    OnlyMarketProductIdentity,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
    OnlyResolvedMarketProductBinding,
)

PLUGIN = OnlyMarketProductPluginId("test-t2-market")
PRODUCT = OnlyMarketProductId("TEST_T2_MARKET")
VERSION = OnlyMarketProductVersion("1")
INSTRUMENT = OnlyInstrumentId.parse("TEST.T2")
DAY = OnlyTradingDay(date(2026, 8, 11))


def _identity(kind: str, name: str) -> OnlyMarketProductAuthorityIdentity:
    return OnlyMarketProductAuthorityIdentity(kind, name, "1", only_canonical_fingerprint((kind, name, "1")))


@dataclass(frozen=True, slots=True)
class _Reference:
    content_fingerprint: str = only_canonical_fingerprint(("TEST.T2", "reference"))


@dataclass(frozen=True, slots=True)
class _ReferenceAuthority:
    identity: OnlyMarketProductAuthorityIdentity = _identity("REFERENCE", "test-t2-reference")

    def resolve(self, instrument_id: OnlyInstrumentId, trading_day: OnlyTradingDay) -> _Reference:
        assert (instrument_id, trading_day) == (INSTRUMENT, DAY)
        return _Reference()


@dataclass(frozen=True, slots=True)
class _Compiler:
    identity: OnlyMarketProductAuthorityIdentity = _identity("POLICY_COMPILER", "test-t2-compiler")

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> OnlyCompiledMarketPolicy:
        reference = request.reference_authority.resolve(request.instrument_id, request.trading_day)
        immediate = OnlySettlementRule(OnlySettlementTiming.IMMEDIATE)
        t2 = OnlySettlementRule(OnlySettlementTiming.T_PLUS_N, 2)
        return OnlyCompiledMarketPolicy.create(
            instrument_id=request.instrument_id,
            trading_day=request.trading_day,
            reference_fingerprint=reference.content_fingerprint,
            compiler=self.identity,
            instrument_terms=OnlyCompiledInstrumentMarketTerms(
                "USD", Decimal("3"), OnlyInstrumentTradingStatus.TRADABLE
            ),
            session_policy=OnlyTradingSessionModel(
                "TEST_SESSION",
                "UTC",
                (OnlyTradingSessionDefinition("regular", time(0), time(0), OnlyTradingPhase.CONTINUOUS),),
            ),
            price_policy=OnlyCompiledPriceBandPolicy(
                "TEST_T2@1",
                Decimal("0.25"),
                None,
                None,
                None,
                None,
                OnlyPriceBandRoundingMode.HALF_UP_TO_TICK,
            ),
            quantity_policy=OnlyCompiledQuantityPolicy(
                Decimal("7"), Decimal("7"), Decimal("7"), Decimal("7"), False, None, False
            ),
            position_policy=OnlyPositionAccountingModel(OnlyMarketPositionMode.LONG_ONLY),
            short_policy=OnlyShortSellingRule(OnlyShortSellingMode.DISABLED),
            settlement_policy=OnlySettlementModel("TEST_T2", t2, t2, t2, immediate),
            margin_policy=None,
        )


@dataclass(frozen=True, slots=True)
class _Resources:
    reference: _ReferenceAuthority
    fees: OnlyMarketFeePack

    def require_reference_authority(self, resource_id: str) -> _ReferenceAuthority:
        assert resource_id == "test-t2-reference"
        return self.reference

    def require_market_fee_pack(self, pack_id: str, pack_version: str) -> OnlyMarketFeePack:
        assert (pack_id, pack_version) == ("TEST_T2_FEES", "1")
        return self.fees


@dataclass(frozen=True, slots=True)
class _Factory:
    plugin_id: OnlyMarketProductPluginId = PLUGIN
    compiler: _Compiler = _Compiler()

    def resolve(
        self,
        config: OnlyMarketProductConfig,
        context: OnlyMarketProductResolutionContext,
    ) -> OnlyResolvedMarketProductBinding:
        reference = context.resources.require_reference_authority("test-t2-reference")
        fees = context.resources.require_market_fee_pack("TEST_T2_FEES", "1")
        product = OnlyMarketProductIdentity(config.product_id, config.product_version)
        identity = OnlyMarketProductCompositionIdentity.create(
            product_identity=product,
            reference_authority=reference.identity,
            policy_compiler=self.compiler.identity,
            market_fee_pack=fees.identity,
            effective_config_fingerprint=only_canonical_fingerprint(()),
        )
        return OnlyResolvedMarketProductBinding(product, self.plugin_id, reference, self.compiler, fees, identity)


def test_third_market_registers_and_compiles_without_core_behavior_branch() -> None:
    fees = OnlyMarketFeePack.create(
        pack_id="TEST_T2_FEES",
        pack_version="1",
        compatible_market_profiles=("TEST_T2_MARKET",),
        schedules=(),
    )
    context = OnlyMarketProductResolutionContext(_Resources(_ReferenceAuthority(), fees))
    config = OnlyMarketProductConfig(PLUGIN, PRODUCT, VERSION, OnlyCanonicalMarketProductConfig({}))
    registry = OnlyMarketProductFactoryRegistry()
    registry.register(_Factory())
    binding = registry.resolve(config, context)
    policy = binding.policy_compiler.compile(
        OnlyMarketPolicyCompilationRequest(INSTRUMENT, DAY, binding.reference_authority)
    )

    assert policy.price_policy.tick_size == Decimal("0.25")
    assert policy.quantity_policy.buy_quantity_increment == Decimal("7")
    assert policy.settlement_policy.compile().legal_settlement_lag == 2
