"""Facts and aggregates must preserve their complete immutable owning scope."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain import fee as fees
from onlyalpha.domain.account import OnlyAccount, OnlyPnL, OnlyPosition
from onlyalpha.domain.enums import OnlyMarginMode, OnlyPositionDirection
from onlyalpha.domain.errors import OnlySerializationError, OnlyValidationError
from onlyalpha.domain.execution import OnlyCancelOrderRequest, OnlyOrderFill
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyOrderRequestId,
    OnlyPositionId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity


@pytest.mark.parametrize("metadata", [{"nested": {"a": "b"}}, {"count": 1}, {1: "text"}, {"flag": True}])
def test_execution_metadata_rejects_mutable_or_non_string_values(metadata) -> None:
    with pytest.raises(OnlyValidationError):
        OnlyCancelOrderRequest(OnlyOrderRequestId("request"), OnlyOrderId("order"), metadata=metadata)
    fill = OnlyOrderFill(
        OnlyTradeId("trade"),
        OnlyOrderId("order"),
        OnlyPrice(Decimal("1"), 0),
        OnlyQuantity(Decimal("1"), 0),
        OnlyTimestamp(1),
        OnlyTimestamp(1),
    )
    payload = fill.to_dict()
    payload["metadata"] = metadata
    with pytest.raises(OnlySerializationError):
        OnlyOrderFill.from_dict(payload)


def _binding(runtime="runtime"):
    currency = OnlyCurrency("USD", 2)
    account = OnlyAccountId("account")
    instrument = OnlyInstrumentId.parse("A.X")
    scope = fees.OnlyOrderFeeApplicabilityScopeIdentity.create(
        market_product_id="product",
        market="test",
        venue="X",
        instrument_class="asset",
        broker_id="broker",
        account_id=account,
        instrument_id=instrument,
        charge_currency=currency,
    )
    binding = fees.OnlyOrderFeePolicyBinding.create(
        runtime_id=OnlyRuntimeId(runtime),
        account_id=account,
        cluster_id=OnlyClusterId("cluster"),
        order_id=OnlyOrderId("order"),
        instrument_id=instrument,
        market_product_id="product",
        market_product_version="1",
        market_fee_pack=fees.OnlyMarketFeePackIdentity("pack", "1", "a" * 64),
        broker_fee_contract=fees.OnlyBrokerFeeContractIdentity(
            "contract",
            "1",
            "broker",
            fees.OnlyBrokerFeeAccountScope(fees.OnlyBrokerFeeAccountScopeType.ALL_ACCOUNTS),
            "b" * 64,
        ),
        applicability_scope=scope,
        order_fixed_schedules=(),
        fill_effective_families=(),
        charge_currency=currency,
        bound_at=OnlyTimestamp(0),
    )
    subject = fees.OnlyFeeSubject(binding.runtime_id, account, binding.cluster_id, binding.order_id, instrument)
    zero = OnlyMoney(Decimal("0"), currency)
    return fees.OnlyFeeAssessment(
        "assessment", subject, None, (), zero, zero, "a" * 64, "b" * 64, fees.OnlyLocalFeeFinality.ESTIMATED, binding
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtime_id", OnlyRuntimeId("foreign")),
        ("account_id", OnlyAccountId("foreign")),
        ("cluster_id", OnlyClusterId("foreign")),
        ("instrument_id", OnlyInstrumentId.parse("B.X")),
    ],
)
def test_fee_assessment_cannot_cross_binding_scope(field, value) -> None:
    assessment = _binding()
    with pytest.raises(ValueError):
        replace(assessment, subject=replace(assessment.subject, **{field: value}))


def test_fee_assessment_currency_is_bound_to_charge_currency() -> None:
    assessment = _binding()
    zero = OnlyMoney(Decimal(0), OnlyCurrency("EUR", 2))
    with pytest.raises(ValueError):
        replace(assessment, total_charges=zero, total_rebates=zero)


@pytest.mark.parametrize("foreign,duplicate", [(True, False), (False, True)])
def test_account_positions_have_one_owner_and_unique_identity(foreign, duplicate) -> None:
    account = OnlyAccountId("account")
    zero = OnlyMoney(Decimal(0), OnlyCurrency("USD", 2))
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    position = OnlyPosition(
        OnlyPositionId("position"),
        OnlyAccountId("foreign") if foreign else account,
        OnlyInstrumentId.parse("A.X"),
        OnlyPositionDirection.FLAT,
        OnlyQuantity(Decimal(0), 0),
        OnlyQuantity(Decimal(0), 0),
        None,
        OnlyPnL(zero, zero),
        None,
        timestamp,
    )
    with pytest.raises(OnlyValidationError):
        OnlyAccount(
            account, None, OnlyMarginMode.CASH, (), (position, position) if duplicate else (position,), None, timestamp
        )


def test_current_execution_intent_reader_does_not_upgrade_old_schema() -> None:
    from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
    from onlyalpha.domain.trading import OnlyExecutionIntent

    payload = OnlyExecutionIntent.from_offset(side=OnlyOrderSide.BUY, offset=OnlyOffset.OPEN).to_dict()
    payload["schema_version"] = 1
    del payload["position_mode"]
    with pytest.raises(OnlySerializationError):
        OnlyExecutionIntent.from_dict(payload)


@pytest.mark.parametrize("funding", [False, True])
def test_current_market_fact_readers_do_not_upgrade_old_schema(funding) -> None:
    from onlyalpha.domain.market import OnlyFundingRateFact, OnlyReferencePriceFact
    from onlyalpha.domain.trading import OnlyReferencePriceKind

    instant = datetime(2025, 1, 1, tzinfo=UTC)
    instrument = OnlyInstrumentId.parse("A.X")
    fact = (
        OnlyFundingRateFact("fact", instrument, Decimal("0.001"), instant, instant, "source", 1, "v1")
        if funding
        else OnlyReferencePriceFact(
            "fact",
            instrument,
            OnlyReferencePriceKind.MARK,
            OnlyPrice(Decimal(1), 0),
            instant,
            instant,
            "source",
            1,
            "v1",
        )
    )
    payload = fact.to_dict()
    payload["schema_version"] = 1
    del payload["provider_evidence_id"]
    del payload["source_record_hash"]
    with pytest.raises(OnlySerializationError):
        type(fact).from_dict(payload)


def _snapshot():
    from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderType
    from onlyalpha.domain.execution import OnlyOrderRequest
    from onlyalpha.domain.identifiers import OnlyEngineId
    from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
    from onlyalpha.order.manager import OnlyOrderManager

    runtime = OnlyRuntimeId("runtime")
    manager = OnlyOrderManager(
        OnlyEngineId("engine"),
        runtime,
        OnlySequenceOrderIdGenerator(runtime),
        OnlySequenceClientOrderIdGenerator(runtime),
    )
    request = OnlyOrderRequest(
        OnlyOrderRequestId("request"),
        OnlyInstrumentId.parse("A.X"),
        OnlyOrderSide.BUY,
        OnlyOrderType.MARKET,
        OnlyQuantity(Decimal(1), 0),
    )
    return manager.create_order(request, OnlyClusterId("cluster"), OnlyAccountId("account"), OnlyTimestamp(0)).snapshot


def test_current_order_snapshot_reader_does_not_upgrade_old_schema() -> None:
    snapshot = _snapshot()
    payload = snapshot.to_dict()
    payload["schema_version"] = 3
    del payload["execution_intent"]
    with pytest.raises(OnlySerializationError):
        type(snapshot).from_dict(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtime_id", OnlyRuntimeId("foreign")),
        ("account_id", OnlyAccountId("foreign")),
        ("cluster_id", OnlyClusterId("foreign")),
        ("instrument_id", OnlyInstrumentId.parse("B.X")),
    ],
)
def test_order_snapshot_fee_contract_is_bound_to_complete_order_scope(field, value) -> None:
    snapshot = _snapshot_with_fee_contract()
    with pytest.raises(OnlyValidationError):
        replace(snapshot, **{field: value})


def _snapshot_with_fee_contract():
    assessment = _binding()
    binding = assessment.binding
    estimate = fees.OnlyOrderFeeEstimate(
        assessment, assessment, assessment.total_charges, assessment.total_rebates, "d" * 64
    )
    zero = assessment.total_charges
    plan = fees.OnlyOrderFundingPlan(
        binding.order_id, zero, zero, zero, binding.fingerprint, estimate.assumptions_fingerprint
    )
    snapshot = replace(
        _snapshot(), order_id=binding.order_id, fee_policy_binding=binding, fee_estimate=estimate, funding_plan=plan
    )
    return snapshot


@pytest.mark.parametrize("field", ["binding_fingerprint", "estimate_fingerprint"])
def test_order_funding_plan_must_match_installed_artifacts(field) -> None:
    snapshot = _snapshot_with_fee_contract()
    with pytest.raises(OnlyValidationError):
        replace(snapshot, funding_plan=replace(snapshot.funding_plan, **{field: "0" * 64}))


def test_order_fee_estimate_must_match_installed_binding() -> None:
    snapshot = _snapshot_with_fee_contract()
    assessment = _binding(runtime="foreign")
    estimate = fees.OnlyOrderFeeEstimate(
        assessment, assessment, assessment.total_charges, assessment.total_rebates, "d" * 64
    )
    with pytest.raises(OnlyValidationError):
        replace(snapshot, fee_estimate=estimate)


def test_fee_estimate_cannot_mix_different_subjects_or_bindings() -> None:
    expected, maximum = _binding(), _binding(runtime="foreign")
    with pytest.raises(ValueError):
        fees.OnlyOrderFeeEstimate(expected, maximum, maximum.total_charges, expected.total_rebates, "d" * 64)


@pytest.mark.parametrize("field", ["broker_id", "account_scope"])
def test_order_fee_binding_broker_contract_must_match_applicability(field) -> None:
    from dataclasses import fields

    binding = _binding().binding
    contract = binding.broker_fee_contract
    mismatch = (
        "foreign"
        if field == "broker_id"
        else fees.OnlyBrokerFeeAccountScope(fees.OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT, OnlyAccountId("foreign"))
    )
    arguments = {item.name: getattr(binding, item.name) for item in fields(binding) if item.name != "fingerprint"}
    arguments["broker_fee_contract"] = replace(contract, **{field: mismatch})
    with pytest.raises(ValueError):
        fees.OnlyOrderFeePolicyBinding.create(**arguments)


@pytest.mark.parametrize("field", ["minimum_notional", "maximum_notional"])
def test_instrument_notional_limit_uses_quote_currency(equity, field: str) -> None:
    with pytest.raises(OnlyValidationError, match="quote currency"):
        replace(equity, **{field: OnlyMoney(Decimal("1"), OnlyCurrency("USD", 2))})


def test_pnl_requires_explicit_cross_currency_conversion(equity) -> None:
    from onlyalpha.domain.account import OnlyPnLCalculator

    cross_currency = replace(equity, settlement_currency=OnlyCurrency("USD", 2))
    with pytest.raises(OnlyValidationError, match="conversion"):
        OnlyPnLCalculator.unrealized(
            cross_currency,
            OnlyPositionDirection.LONG,
            OnlyQuantity(Decimal("2"), 0),
            OnlyPrice(Decimal("10.00"), 2),
            OnlyPrice(Decimal("12.50"), 2),
        )


def test_pnl_flat_direction_cannot_have_nonzero_quantity(equity) -> None:
    from onlyalpha.domain.account import OnlyPnLCalculator

    with pytest.raises(OnlyValidationError, match="flat"):
        OnlyPnLCalculator.unrealized(
            equity,
            OnlyPositionDirection.FLAT,
            OnlyQuantity(Decimal("2"), 0),
            OnlyPrice(Decimal("10.00"), 2),
            OnlyPrice(Decimal("12.50"), 2),
        )
    zero = OnlyPnLCalculator.unrealized(
        equity,
        OnlyPositionDirection.FLAT,
        OnlyQuantity(Decimal("0"), 0),
        OnlyPrice(Decimal("0.00"), 2),
        OnlyPrice(Decimal("0.00"), 2),
    )
    assert zero == OnlyMoney(Decimal("0.00"), equity.settlement_currency)


@pytest.mark.parametrize("tag", [[], {}, 1, True])
def test_order_tags_cannot_contain_mutable_or_non_string_values(instrument_id, tag) -> None:
    from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderType
    from onlyalpha.domain.execution import OnlyOrderRequest

    with pytest.raises(OnlyValidationError):
        OnlyOrderRequest(
            OnlyOrderRequestId("request"),
            instrument_id,
            OnlyOrderSide.BUY,
            OnlyOrderType.MARKET,
            OnlyQuantity(Decimal("1"), 0),
            tags=(tag,),
        )


@pytest.mark.parametrize("field", ["order_fixed_schedules", "fill_effective_families"])
def test_fee_binding_rejects_mutable_schedule_containers(field) -> None:
    from dataclasses import fields

    binding = _binding().binding
    values = {item.name: getattr(binding, item.name) for item in fields(binding)}
    values.pop("fingerprint")
    values[field] = []
    with pytest.raises(OnlyValidationError, match="immutable tuple"):
        fees.OnlyOrderFeePolicyBinding.create(**values)
    with pytest.raises(OnlyValidationError, match="immutable tuple"):
        replace(binding, **{field: []})


def test_domain_collections_cannot_retain_caller_owned_lists(equity) -> None:
    from dataclasses import fields
    from datetime import date, time
    from typing import get_origin, get_type_hints

    from onlyalpha.domain.account import OnlyPortfolio
    from onlyalpha.domain.calendar import (
        OnlySessionProfile,
        OnlySessionSchedule,
        OnlyTradingCalendar,
        OnlyTradingCalendarCatalog,
        OnlyTradingSession,
    )
    from onlyalpha.domain.catalog import OnlyInstrumentCatalog
    from onlyalpha.domain.enums import OnlyBookType
    from onlyalpha.domain.identifiers import OnlyCalendarId, OnlySessionProfileId, OnlyVenueId
    from onlyalpha.domain.market import OnlyOrderBook
    from onlyalpha.domain.market_rules import (
        OnlyFeeScheduleCatalog,
        OnlyPriceLadder,
        OnlySettlementRule,
        OnlyValidationResult,
    )
    from onlyalpha.domain.time import OnlyTimeZone, OnlyTradingDay

    now = datetime(2025, 1, 1, tzinfo=UTC)
    zero = OnlyMoney(Decimal(0), OnlyCurrency("USD", 2))
    position = OnlyPosition(
        OnlyPositionId("position"),
        OnlyAccountId("account"),
        OnlyInstrumentId.parse("A.X"),
        OnlyPositionDirection.FLAT,
        OnlyQuantity(Decimal(0), 0),
        OnlyQuantity(Decimal(0), 0),
        None,
        OnlyPnL(zero, zero),
        None,
        now,
    )
    account = OnlyAccount(position.account_id, None, OnlyMarginMode.CASH, (), (position,), None, now)
    session = OnlyTradingSession("day", time(9), time(17))
    calendar = OnlyTradingCalendar(OnlyCalendarId("calendar"), OnlyVenueId("X"), OnlyTimeZone("UTC"), (session,))
    assessment = _binding()
    examples = [
        position,
        account,
        OnlyPortfolio((account,), None, None, now),
        OnlyInstrumentCatalog((equity,)),
        assessment,
        assessment.binding,
        OnlyOrderBook(equity.instrument_id, OnlyBookType.L2, (), (), 0, now),
        OnlySessionSchedule(OnlyTradingDay(date(2025, 1, 1)), (session,)),
        OnlySessionProfile(OnlySessionProfileId("profile"), (session,)),
        calendar,
        OnlyTradingCalendarCatalog((calendar,)),
        OnlyValidationResult(),
        OnlySettlementRule(0),
        OnlyPriceLadder(((None, Decimal("0.01")),)),
        OnlyFeeScheduleCatalog(()),
    ]
    assert OnlyValidationResult().is_valid
    assert not OnlyValidationResult(("invalid",)).is_valid
    for example in examples:
        annotations = get_type_hints(type(example))
        for field in fields(example):
            if get_origin(annotations[field.name]) is tuple:
                values = list(getattr(example, field.name))
                with pytest.raises(OnlyValidationError, match="immutable tuple"):
                    replace(example, **{field.name: values})
    with pytest.raises(OnlyValidationError, match="immutable tuple"):
        OnlyPriceLadder(([None, Decimal("0.01")],))
