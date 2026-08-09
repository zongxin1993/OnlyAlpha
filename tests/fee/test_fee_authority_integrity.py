from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import (
    OnlyAssetClass,
    OnlyContractType,
    OnlyMarketType,
    OnlySettlementType,
)
from onlyalpha.domain.errors import OnlySerializationError
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRawSymbol,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.instrument import OnlyEquity, OnlyFuture
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.fee import (
    OnlyBrokerFeeAccountScope,
    OnlyBrokerFeeAccountScopeType,
    OnlyBrokerFeeApplicabilityContext,
    OnlyBrokerFeeContract,
    OnlyBrokerFeeContractRegistry,
    OnlyBrokerFeeSchedule,
    OnlyBrokerFeeScheduleRegistry,
    OnlyFeeAuthority,
    OnlyFeeBasisValues,
    OnlyFeeCalculationBasis,
    OnlyFeeCalculationPipeline,
    OnlyFeeCalculationScope,
    OnlyFeeEconomicDirection,
    OnlyFeeEngine,
    OnlyFeeFormula,
    OnlyFeePolicyResolution,
    OnlyFeeRateTerm,
    OnlyFeeResolutionPolicy,
    OnlyFeeRoundingMode,
    OnlyFeeRoundingPolicy,
    OnlyFeeRule,
    OnlyFeeScheduleAuthority,
    OnlyFeeSubject,
    OnlyFeeType,
    OnlyGenericCashFeeBasisProvider,
    OnlyGenericFuturesFeeBasisProvider,
    OnlyLocalFeeFinality,
    OnlyMarketFeeApplicabilityContext,
    OnlyMarketFeePack,
    OnlyMarketFeePackRegistry,
    OnlyMarketFeeSchedule,
    OnlyMarketFeeScheduleRegistry,
    OnlyOrderFeeApplicabilityScopeIdentity,
    OnlyOrderFeePolicyBinding,
    OnlyResolvedFeePolicySet,
    OnlyTradeFeeAssessmentRequest,
)

CNY = OnlyCurrency("CNY", 2)
ACCOUNT = OnlyAccountId("account-a")
INSTRUMENT = OnlyInstrumentId.parse("TEST.XSHG")
DAY_ONE = OnlyTradingDay(date(2026, 1, 5))
DAY_TWO = OnlyTradingDay(date(2026, 1, 6))


def _rule(
    authority: OnlyFeeAuthority,
    *,
    resolution: OnlyFeeResolutionPolicy = OnlyFeeResolutionPolicy.FILL_EFFECTIVE,
) -> OnlyFeeRule:
    return OnlyFeeRule(
        f"{authority.value.lower()}-rule",
        OnlyFeeType.BROKER_COMMISSION if authority is OnlyFeeAuthority.BROKER else OnlyFeeType.EXCHANGE_FEE,
        authority,
        OnlyFeeEconomicDirection.CHARGE,
        OnlyFeeFormula((OnlyFeeRateTerm(OnlyFeeCalculationBasis.NOTIONAL, Decimal("0.001")),)),
        OnlyFeeCalculationScope.FILL,
        resolution,
        None,
        None,
        None,
        None,
        None,
        OnlyFeeRoundingPolicy(Decimal("0.01"), OnlyFeeRoundingMode.HALF_EVEN),
        OnlyFeeCalculationPipeline.ROUND_THEN_BOUNDS,
    )


def _market_schedule(
    version: str = "1",
    *,
    schedule_id: str = "STANDARD",
    effective_from: date = DAY_ONE.value,
    effective_to: date | None = None,
    venue: str | None = "XSHG",
    resolution: OnlyFeeResolutionPolicy = OnlyFeeResolutionPolicy.FILL_EFFECTIVE,
) -> OnlyMarketFeeSchedule:
    return OnlyMarketFeeSchedule(
        schedule_id,
        version,
        effective_from,
        effective_to,
        CNY,
        "Market Conformance",
        (_rule(OnlyFeeAuthority.MARKET, resolution=resolution),),
        "GENERIC",
        venue,
        "CASH",
    )


def _broker_schedule(
    version: str = "1",
    *,
    schedule_id: str = "STANDARD",
    broker_id: str = "broker-a",
    account_scope: OnlyBrokerFeeAccountScope | None = None,
) -> OnlyBrokerFeeSchedule:
    return OnlyBrokerFeeSchedule(
        schedule_id,
        version,
        DAY_ONE.value,
        None,
        CNY,
        "Broker Contract",
        (_rule(OnlyFeeAuthority.BROKER),),
        broker_id,
        account_scope or OnlyBrokerFeeAccountScope(OnlyBrokerFeeAccountScopeType.ALL_ACCOUNTS),
    )


def _contexts() -> tuple[OnlyMarketFeeApplicabilityContext, OnlyBrokerFeeApplicabilityContext]:
    return (
        OnlyMarketFeeApplicabilityContext(DAY_ONE, "GENERIC_T0_CASH", "GENERIC", "XSHG", "CASH", INSTRUMENT),
        OnlyBrokerFeeApplicabilityContext(DAY_ONE, "broker-a", ACCOUNT, INSTRUMENT),
    )


def _authorities() -> tuple[OnlyMarketFeePack, OnlyBrokerFeeContract]:
    market = _market_schedule(resolution=OnlyFeeResolutionPolicy.ORDER_FIXED)
    broker = _broker_schedule()
    pack = OnlyMarketFeePack.create(
        pack_id="TEST_MARKET_PACK",
        pack_version="1",
        compatible_market_profiles=("GENERIC_T0_CASH",),
        schedules=(market,),
    )
    contract = OnlyBrokerFeeContract.create(
        contract_id="TEST_BROKER_CONTRACT",
        contract_version="1",
        broker_id="broker-a",
        account_scope=broker.account_scope,
        schedules=(broker,),
    )
    return pack, contract


def _binding(order_id: str = "order-a") -> tuple[OnlyOrderFeePolicyBinding, OnlyFeePolicyResolution]:
    pack, contract = _authorities()
    market, broker = pack.schedules[0], contract.schedules[0]
    scope = OnlyOrderFeeApplicabilityScopeIdentity.create(
        market_profile_id="GENERIC_T0_CASH",
        market="GENERIC",
        venue="XSHG",
        instrument_class="CASH",
        broker_id="broker-a",
        account_id=ACCOUNT,
        instrument_id=INSTRUMENT,
        charge_currency=CNY,
    )
    binding = OnlyOrderFeePolicyBinding.create(
        runtime_id=OnlyRuntimeId("runtime"),
        account_id=ACCOUNT,
        cluster_id=OnlyClusterId("cluster"),
        order_id=OnlyOrderId(order_id),
        instrument_id=INSTRUMENT,
        market_profile_id="GENERIC_T0_CASH",
        market_profile_version="1",
        market_fee_pack=pack.identity,
        broker_fee_contract=contract.identity,
        applicability_scope=scope,
        order_fixed_schedules=(market.identity,),
        fill_effective_families=(broker.family_identity,),
        charge_currency=CNY,
        bound_at=OnlyTimestamp.from_unix_nanos(1),
    )
    policies = OnlyResolvedFeePolicySet.create((*market.resolved_policies(), *broker.resolved_policies()))
    resolution = OnlyFeePolicyResolution.create(
        binding_fingerprint=binding.fingerprint,
        market_fee_pack=pack.identity,
        broker_fee_contract=contract.identity,
        scope_fingerprint=scope.fingerprint,
        resolved_schedules=(broker.identity, market.identity),
        policies=policies,
        trading_day=DAY_ONE,
    )
    return binding, resolution


def test_market_and_broker_same_schedule_id_have_distinct_namespaces() -> None:
    market = _market_schedule()
    broker = _broker_schedule()

    assert market.identity.authority is OnlyFeeScheduleAuthority.MARKET
    assert broker.identity.authority is OnlyFeeScheduleAuthority.BROKER
    assert market.identity != broker.identity


def test_schedule_scope_is_a_real_applicability_condition() -> None:
    market_context, broker_context = _contexts()
    assert _market_schedule().matches(market_context)
    assert not _market_schedule(venue="XSHE").matches(market_context)
    assert _broker_schedule().matches(broker_context)
    assert not _broker_schedule(broker_id="broker-b").matches(broker_context)


def test_registry_rejects_market_broker_and_account_scope_drift() -> None:
    market = OnlyMarketFeeScheduleRegistry()
    market.register(_market_schedule("1", venue="XSHG"))
    with pytest.raises(ValueError, match="FEE_SCHEDULE_SCOPE_DRIFT"):
        market.register(_market_schedule("2", venue="XSHE"))

    broker = OnlyBrokerFeeScheduleRegistry()
    broker.register(_broker_schedule("1"))
    with pytest.raises(ValueError, match="FEE_SCHEDULE_SCOPE_DRIFT"):
        broker.register(_broker_schedule("2", broker_id="broker-b"))

    exact = OnlyBrokerFeeAccountScope(OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT, ACCOUNT)
    broker = OnlyBrokerFeeScheduleRegistry()
    broker.register(_broker_schedule("1"))
    with pytest.raises(ValueError, match="FEE_SCHEDULE_SCOPE_DRIFT"):
        broker.register(_broker_schedule("2", account_scope=exact))


def test_effective_family_requires_exactly_one_version() -> None:
    context, _ = _contexts()
    registry = OnlyMarketFeeScheduleRegistry()
    first = _market_schedule("1")
    registry.register(first)
    with pytest.raises(ValueError, match="FEE_SCHEDULE_AMBIGUOUS"):
        registry.register(_market_schedule("2"))

    empty = OnlyMarketFeeScheduleRegistry()
    with pytest.raises(ValueError, match="FEE_SCHEDULE_NOT_FOUND"):
        empty.resolve_family(first.family_identity, context)


def test_fill_effective_selects_day_version_while_order_fixed_remains_exact() -> None:
    v1 = _market_schedule("1", effective_to=DAY_TWO.value)
    v2 = _market_schedule("2", effective_from=DAY_TWO.value)
    registry = OnlyMarketFeeScheduleRegistry()
    registry.register(v2)
    registry.register(v1)
    day_two_context = replace(_contexts()[0], trading_day=DAY_TWO)

    assert registry.resolve_family(v1.family_identity, day_two_context).version == "2"
    assert registry.resolve_version(v1.identity).version == "1"


def test_pack_contract_registration_and_compatibility_fail_closed() -> None:
    pack, contract = _authorities()
    packs = OnlyMarketFeePackRegistry()
    packs.register(pack)
    with pytest.raises(ValueError, match="MARKET_FEE_PACK_DUPLICATE_VERSION"):
        packs.register(pack)
    with pytest.raises(ValueError, match="MARKET_FEE_PACK_NOT_INSTALLED"):
        packs.require("UNKNOWN", "1")

    contracts = OnlyBrokerFeeContractRegistry()
    contracts.register(contract)
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_DUPLICATE_VERSION"):
        contracts.register(contract)
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_BROKER_INCOMPATIBLE"):
        contract.validate_compatibility(broker_id="broker-b", account_id=ACCOUNT)

    incompatible_pack = OnlyMarketFeePack.create(
        pack_id="INCOMPATIBLE_MARKET_PACK",
        pack_version="1",
        compatible_market_profiles=("ANOTHER_PROFILE",),
        schedules=pack.schedules,
    )
    with pytest.raises(ValueError, match="MARKET_FEE_PACK_PROFILE_INCOMPATIBLE"):
        incompatible_pack.validate_compatibility("GENERIC_T0_CASH")

    exact_scope = OnlyBrokerFeeAccountScope(OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT, ACCOUNT)
    exact_contract = OnlyBrokerFeeContract.create(
        contract_id="EXACT_ACCOUNT_CONTRACT",
        contract_version="1",
        broker_id="broker-a",
        account_scope=exact_scope,
        schedules=(_broker_schedule(account_scope=exact_scope),),
    )
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_ACCOUNT_INCOMPATIBLE"):
        exact_contract.validate_compatibility(broker_id="broker-a", account_id=OnlyAccountId("account-b"))


def test_same_authority_identity_with_different_payload_is_a_conflict() -> None:
    first, contract = _authorities()
    changed = OnlyMarketFeePack.create(
        pack_id=first.pack_id,
        pack_version=first.pack_version,
        compatible_market_profiles=first.compatible_market_profiles,
        schedules=(_market_schedule(schedule_id="CHANGED"),),
    )
    packs = OnlyMarketFeePackRegistry()
    packs.register(first)
    with pytest.raises(ValueError, match="MARKET_FEE_PACK_FINGERPRINT_CONFLICT"):
        packs.register(changed)

    changed_contract = OnlyBrokerFeeContract.create(
        contract_id=contract.contract_id,
        contract_version=contract.contract_version,
        broker_id=contract.broker_id,
        account_scope=contract.account_scope,
        schedules=(_broker_schedule(schedule_id="CHANGED"),),
    )
    contracts = OnlyBrokerFeeContractRegistry()
    contracts.register(contract)
    with pytest.raises(ValueError, match="BROKER_FEE_CONTRACT_FINGERPRINT_CONFLICT"):
        contracts.register(changed_contract)


def test_binding_v2_round_trip_and_old_schema_rejection() -> None:
    binding, _ = _binding()
    assert OnlyOrderFeePolicyBinding.from_json(binding.to_json()) == binding
    old = binding.to_dict()
    old["schema_version"] = 1
    with pytest.raises(OnlySerializationError, match="UNSUPPORTED_ORDER_FEE_BINDING_SCHEMA"):
        OnlyOrderFeePolicyBinding.from_dict(old)


def test_binding_v2_rejects_every_authority_tamper_dimension() -> None:
    binding, _ = _binding()
    with pytest.raises(ValueError, match="ORDER_FEE_BINDING_CONFLICT"):
        replace(binding, market_fee_pack=replace(binding.market_fee_pack, fingerprint="1" * 64))
    with pytest.raises(ValueError, match="ORDER_FEE_BINDING_CONFLICT"):
        replace(binding, broker_fee_contract=replace(binding.broker_fee_contract, fingerprint="1" * 64))
    with pytest.raises(ValueError, match="order fee applicability account conflicts"):
        replace(binding, account_id=OnlyAccountId("account-b"))
    with pytest.raises(ValueError, match="order fee applicability instrument conflicts"):
        replace(binding, instrument_id=OnlyInstrumentId.parse("OTHER.XSHG"))
    with pytest.raises(ValueError, match="ORDER_FEE_SCOPE_AUTHORITY_CHANGED"):
        replace(binding.applicability_scope, fingerprint="1" * 64)
    with pytest.raises(ValueError, match="ORDER_FEE_BINDING_CONFLICT"):
        replace(
            binding,
            order_fixed_schedules=(
                replace(binding.order_fixed_schedules[0], authority=OnlyFeeScheduleAuthority.BROKER),
            ),
        )
    with pytest.raises(ValueError, match="ORDER_FEE_BINDING_CONFLICT"):
        replace(
            binding,
            order_fixed_schedules=(replace(binding.order_fixed_schedules[0], version="2"),),
        )
    with pytest.raises(ValueError, match="ORDER_FEE_BINDING_CONFLICT"):
        replace(
            binding,
            fill_effective_families=(replace(binding.fill_effective_families[0], schedule_id="OTHER"),),
        )


def test_engine_rejects_cross_binding_even_when_economics_match() -> None:
    binding_a, resolution_a = _binding("order-a")
    binding_b, _ = _binding("order-b")
    basis = OnlyFeeBasisValues(OnlyMoney(Decimal("1000.00"), CNY), Decimal("100"), Decimal(0))
    request = OnlyTradeFeeAssessmentRequest(
        OnlyFeeSubject(
            binding_b.runtime_id,
            binding_b.account_id,
            binding_b.cluster_id,
            binding_b.order_id,
            binding_b.instrument_id,
        ),
        OnlyTradeId("trade"),
        basis,
        basis,
        DAY_ONE,
        None,
        OnlyLocalFeeFinality.MODEL_CONFIRMED,
        binding_b,
        resolution_a,
    )
    with pytest.raises(ValueError, match="ORDER_FEE_POLICY_AUTHORITY_CONFLICT"):
        OnlyFeeEngine().assess_trade(request)


def test_registration_order_does_not_change_policy_or_resolution_fingerprint() -> None:
    binding, _ = _binding()
    pack, contract = _authorities()
    schedules = (pack.schedules[0], contract.schedules[0])
    left = OnlyResolvedFeePolicySet.create((*schedules[0].resolved_policies(), *schedules[1].resolved_policies()))
    right = OnlyResolvedFeePolicySet.create((*schedules[1].resolved_policies(), *schedules[0].resolved_policies()))
    assert left.fingerprint == right.fingerprint
    left_resolution = OnlyFeePolicyResolution.create(
        binding_fingerprint=binding.fingerprint,
        market_fee_pack=pack.identity,
        broker_fee_contract=contract.identity,
        scope_fingerprint=binding.applicability_scope.fingerprint,
        resolved_schedules=(schedules[0].identity, schedules[1].identity),
        policies=left,
        trading_day=DAY_ONE,
    )
    right_resolution = OnlyFeePolicyResolution.create(
        binding_fingerprint=binding.fingerprint,
        market_fee_pack=pack.identity,
        broker_fee_contract=contract.identity,
        scope_fingerprint=binding.applicability_scope.fingerprint,
        resolved_schedules=(schedules[1].identity, schedules[0].identity),
        policies=right,
        trading_day=DAY_ONE,
    )
    assert left_resolution.resolution_fingerprint == right_resolution.resolution_fingerprint


@pytest.mark.exhaustive
def test_authority_proof_is_deterministic_across_repeated_registration_orders() -> None:
    binding, _ = _binding()
    pack, contract = _authorities()
    basis = OnlyFeeBasisValues(OnlyMoney(Decimal("1000.00"), CNY), Decimal("100"), Decimal(0))
    binding_jsons: set[str] = set()
    binding_fingerprints: set[str] = set()
    resolution_fingerprints: set[str] = set()
    policy_fingerprints: set[str] = set()
    assessment_ids: set[str] = set()
    schedules = (pack.schedules[0], contract.schedules[0])
    for index in range(100):
        ordered = schedules if index % 2 == 0 else tuple(reversed(schedules))
        policies = OnlyResolvedFeePolicySet.create(
            tuple(policy for schedule in ordered for policy in schedule.resolved_policies())
        )
        resolution = OnlyFeePolicyResolution.create(
            binding_fingerprint=binding.fingerprint,
            market_fee_pack=pack.identity,
            broker_fee_contract=contract.identity,
            scope_fingerprint=binding.applicability_scope.fingerprint,
            resolved_schedules=tuple(schedule.identity for schedule in ordered),
            policies=policies,
            trading_day=DAY_ONE,
        )
        assessment = OnlyFeeEngine().assess_trade(
            OnlyTradeFeeAssessmentRequest(
                OnlyFeeSubject(
                    binding.runtime_id,
                    binding.account_id,
                    binding.cluster_id,
                    binding.order_id,
                    binding.instrument_id,
                ),
                OnlyTradeId("trade"),
                basis,
                basis,
                DAY_ONE,
                None,
                OnlyLocalFeeFinality.MODEL_CONFIRMED,
                binding,
                resolution,
            )
        )
        binding_jsons.add(binding.to_json())
        binding_fingerprints.add(binding.fingerprint)
        resolution_fingerprints.add(resolution.resolution_fingerprint)
        policy_fingerprints.add(policies.fingerprint)
        assessment_ids.add(assessment.assessment_id)
    assert tuple(
        map(len, (binding_jsons, binding_fingerprints, resolution_fingerprints, policy_fingerprints, assessment_ids))
    ) == (
        1,
        1,
        1,
        1,
        1,
    )


@pytest.mark.recovery
def test_restored_binding_keeps_order_fixed_exact_and_fill_effective_family_after_version_addition() -> None:
    fixed_v1 = _market_schedule(
        "1",
        schedule_id="ORDER_FIXED",
        effective_to=DAY_TWO.value,
        resolution=OnlyFeeResolutionPolicy.ORDER_FIXED,
    )
    fixed_v2 = _market_schedule(
        "2",
        schedule_id="ORDER_FIXED",
        effective_from=DAY_TWO.value,
        resolution=OnlyFeeResolutionPolicy.ORDER_FIXED,
    )
    effective_v1 = _broker_schedule("1", schedule_id="FILL_EFFECTIVE")
    effective_v2 = replace(
        _broker_schedule("2", schedule_id="FILL_EFFECTIVE"),
        effective_from=DAY_TWO.value,
    )
    effective_v1 = replace(effective_v1, effective_to=DAY_TWO.value)
    pack = OnlyMarketFeePack.create(
        pack_id="RESTART_PACK",
        pack_version="1",
        compatible_market_profiles=("GENERIC_T0_CASH",),
        schedules=(fixed_v1, fixed_v2),
    )
    contract = OnlyBrokerFeeContract.create(
        contract_id="RESTART_CONTRACT",
        contract_version="1",
        broker_id="broker-a",
        account_scope=effective_v1.account_scope,
        schedules=(effective_v1, effective_v2),
    )
    scope = OnlyOrderFeeApplicabilityScopeIdentity.create(
        market_profile_id="GENERIC_T0_CASH",
        market="GENERIC",
        venue="XSHG",
        instrument_class="CASH",
        broker_id="broker-a",
        account_id=ACCOUNT,
        instrument_id=INSTRUMENT,
        charge_currency=CNY,
    )
    checkpoint_binding = OnlyOrderFeePolicyBinding.create(
        runtime_id=OnlyRuntimeId("runtime"),
        account_id=ACCOUNT,
        cluster_id=OnlyClusterId("cluster"),
        order_id=OnlyOrderId("order"),
        instrument_id=INSTRUMENT,
        market_profile_id="GENERIC_T0_CASH",
        market_profile_version="1",
        market_fee_pack=pack.identity,
        broker_fee_contract=contract.identity,
        applicability_scope=scope,
        order_fixed_schedules=(fixed_v1.identity,),
        fill_effective_families=(effective_v1.family_identity,),
        charge_currency=CNY,
        bound_at=OnlyTimestamp.from_unix_nanos(1),
    )
    restored = OnlyOrderFeePolicyBinding.from_json(checkpoint_binding.to_json())
    market_registry = OnlyMarketFeeScheduleRegistry()
    broker_registry = OnlyBrokerFeeScheduleRegistry()
    for schedule in reversed(pack.schedules):
        market_registry.register(schedule)
    for schedule in reversed(contract.schedules):
        broker_registry.register(schedule)
    market_context, broker_context = _contexts()
    day_two_broker_context = replace(broker_context, trading_day=DAY_TWO)

    assert restored.fingerprint == checkpoint_binding.fingerprint
    assert market_registry.resolve_version(restored.order_fixed_schedules[0]).version == "1"
    assert broker_registry.resolve_family(restored.fill_effective_families[0], day_two_broker_context).version == "2"


def test_basis_providers_make_cash_and_futures_quantity_semantics_explicit() -> None:
    cash = OnlyEquity(
        instrument_id=INSTRUMENT,
        raw_symbol=OnlyRawSymbol("TEST"),
        market_type=OnlyMarketType.CASH,
        quote_currency=CNY,
        settlement_currency=CNY,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
    )
    cash_basis = OnlyGenericCashFeeBasisProvider().resolve(
        instrument=cash,
        price=OnlyPrice(Decimal("10.00"), 2),
        quantity=Decimal("100"),
    )
    assert cash_basis.notional.amount == Decimal("1000.00")
    assert cash_basis.contracts == 0

    future = OnlyFuture(
        instrument_id=OnlyInstrumentId.parse("FUT.XSHG"),
        raw_symbol=OnlyRawSymbol("FUT"),
        asset_class=OnlyAssetClass.COMMODITY,
        market_type=OnlyMarketType.DERIVATIVE,
        quote_currency=CNY,
        settlement_currency=CNY,
        margin_currency=CNY,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("300"), 0),
        underlying=INSTRUMENT,
        expiration_time=datetime(2026, 12, 31, tzinfo=UTC),
        last_trade_time=datetime(2026, 12, 30, tzinfo=UTC),
        settlement_type=OnlySettlementType.CASH,
        contract_type=OnlyContractType.LINEAR,
    )
    futures_basis = OnlyGenericFuturesFeeBasisProvider().resolve(
        instrument=future,
        price=OnlyPrice(Decimal("10.00"), 2),
        quantity=Decimal("2"),
    )
    assert futures_basis.notional.amount == Decimal("6000.00")
    assert futures_basis.contracts == 2

    unsupported = replace(cash, contract_multiplier=OnlyMultiplier(Decimal("2"), 0))
    with pytest.raises(ValueError, match="FEE_BASIS_UNSUPPORTED"):
        OnlyGenericCashFeeBasisProvider().resolve(
            instrument=unsupported,
            price=OnlyPrice(Decimal("10.00"), 2),
            quantity=Decimal("1"),
        )
