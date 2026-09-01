from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import MethodType, SimpleNamespace

import pytest

from onlyalpha.account.enums import OnlyAccountEconomicCashflowType
from onlyalpha.account.models import OnlyAccountEconomicCashflow
from onlyalpha.data.models import OnlyReferencePriceUpdate
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyFundingRateFact, OnlyReferencePriceFact
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice
from onlyalpha.market.economics import OnlyEconomicModel
from onlyalpha.position.keys import OnlyPositionKey
from onlyalpha.position.models import OnlyPositionSettlementFact
from onlyalpha.runtime.trading_facade import (
    OnlyTradingRuntimeFacade,
    _OnlyEconomicFactApplicationPlan,
    _OnlyStrategyEconomicCashflowApplication,
)
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashEntryType
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyCashFlowId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)
RUNTIME = OnlyRuntimeId("runtime")
ACCOUNT = OnlyAccountId("account")
CLUSTER = OnlyClusterId("cluster")
INSTRUMENT = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
USDT = OnlyCurrency("USDT", 2)


class _IdempotentAccount:
    def __init__(self) -> None:
        self.applied: dict[str, OnlyAccountEconomicCashflow] = {}
        self.effects = 0

    def apply_economic_cashflow(self, cashflow: OnlyAccountEconomicCashflow) -> None:
        existing = self.applied.get(cashflow.cashflow_id)
        if existing is not None:
            if existing != cashflow:
                raise ValueError("ACCOUNT_CONFLICT")
            return
        self.applied[cashflow.cashflow_id] = cashflow
        self.effects += 1


class _FailOnceStrategy:
    def __init__(self) -> None:
        self.failed = False
        self.applied: set[OnlyStrategyCashFlowId] = set()

    def apply_economic_cashflow(
        self,
        _key: OnlyStrategyLedgerKey,
        cashflow_id: OnlyStrategyCashFlowId,
        _amount: OnlyMoney,
        _entry_type: OnlyStrategyCashEntryType,
        _timestamp: OnlyTimestamp,
    ) -> None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("injected strategy failure")
        self.applied.add(cashflow_id)


class _FailOnceAllocation:
    def __init__(self) -> None:
        self.failed = False
        self.effects = 0

    def apply_settlement(self, _settlement: OnlyPositionSettlementFact) -> None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("injected allocation failure")
        self.effects += 1


class _IdempotentPosition:
    def __init__(self) -> None:
        self.applied: set[str] = set()
        self.effects = 0

    def apply_settlement(self, settlement: OnlyPositionSettlementFact) -> None:
        if settlement.settlement_application_id in self.applied:
            return
        self.applied.add(settlement.settlement_application_id)
        self.effects += 1


def _runtime(*, account: object, strategy: object, position: object, allocation: object) -> OnlyTradingRuntimeFacade:
    runtime = object.__new__(OnlyTradingRuntimeFacade)
    runtime._trading_kernel = SimpleNamespace(  # type: ignore[attr-defined]
        services=SimpleNamespace(
            account_manager=account,
            strategy_ledger_manager=strategy,
            position_manager=position,
            allocation_manager=allocation,
        )
    )
    runtime._pending_economic_fact_applications = {}  # type: ignore[attr-defined]
    runtime._reference_price_facts = {}  # type: ignore[attr-defined]
    runtime._funding_rate_facts = {}  # type: ignore[attr-defined]
    runtime._reference_prices_by_boundary = {}  # type: ignore[attr-defined]
    runtime._selected_calendar = SimpleNamespace(  # type: ignore[attr-defined]
        trading_day_at=lambda _timestamp: OnlyTradingDay(date(2026, 9, 1))
    )
    return runtime


def test_funding_retry_completes_without_duplicate_account_effect() -> None:
    account = _IdempotentAccount()
    strategy = _FailOnceStrategy()
    runtime = _runtime(account=account, strategy=strategy, position=object(), allocation=object())
    policy = SimpleNamespace(funding_policy=SimpleNamespace(valuation_price_kind=OnlyReferencePriceKind.MARK))
    runtime.config = SimpleNamespace(  # type: ignore[attr-defined]
        market_rule_engine=SimpleNamespace(compiled_rules=lambda *_args, **_kwargs: policy)
    )
    mark = OnlyReferencePriceFact(
        "mark",
        INSTRUMENT,
        OnlyReferencePriceKind.MARK,
        OnlyPrice(Decimal("100.00"), 2),
        NOW,
        NOW,
        "fixture",
        1,
        "v1",
    )
    funding = OnlyFundingRateFact("funding", INSTRUMENT, Decimal("0.01"), NOW, NOW, "fixture", 2, "v1")
    runtime._reference_prices_by_boundary[
        (  # type: ignore[attr-defined]
            INSTRUMENT,
            OnlyReferencePriceKind.MARK,
            OnlyTimestamp.from_datetime(NOW).unix_nanos,
        )
    ] = mark
    account_cashflow = OnlyAccountEconomicCashflow(
        "funding-cash",
        RUNTIME,
        ACCOUNT,
        OnlyAccountEconomicCashflowType.FUNDING,
        OnlyMoney(Decimal("-1.00"), USDT),
        OnlyTimestamp.from_datetime(NOW),
        funding.fact_id,
        str(INSTRUMENT),
    )
    strategy_cashflow = _OnlyStrategyEconomicCashflowApplication(
        OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, CLUSTER, USDT),
        OnlyStrategyCashFlowId("funding-strategy"),
        OnlyMoney(Decimal("-1.00"), USDT),
        OnlyStrategyCashEntryType.FUNDING,
        OnlyTimestamp.from_datetime(NOW),
    )
    plan = _OnlyEconomicFactApplicationPlan(
        funding.fact_id,
        funding.to_json(),
        "FUNDING",
        (),
        (account_cashflow,),
        (strategy_cashflow,),
    )
    assert _OnlyEconomicFactApplicationPlan.from_json(plan.to_json()) == plan
    runtime._plan_funding_application = MethodType(  # type: ignore[attr-defined]
        lambda _self, _fact, _valuation, _policy: plan,
        runtime,
    )

    with pytest.raises(RuntimeError, match="injected strategy failure"):
        runtime._apply_funding_rate(funding)
    assert funding.fact_id not in runtime._funding_rate_facts  # type: ignore[attr-defined]
    assert account.effects == 1

    runtime._apply_funding_rate(funding)
    assert runtime._funding_rate_facts[funding.fact_id] == funding  # type: ignore[attr-defined]
    assert account.effects == 1
    assert strategy.applied == {OnlyStrategyCashFlowId("funding-strategy")}


def test_restored_pending_funding_plan_is_automatically_forward_recovered() -> None:
    account = _IdempotentAccount()
    strategy = _FailOnceStrategy()
    runtime = _runtime(account=account, strategy=strategy, position=object(), allocation=object())
    policy = SimpleNamespace(funding_policy=SimpleNamespace(valuation_price_kind=OnlyReferencePriceKind.MARK))
    runtime.config = SimpleNamespace(  # type: ignore[attr-defined]
        market_rule_engine=SimpleNamespace(compiled_rules=lambda *_args, **_kwargs: policy)
    )
    mark = OnlyReferencePriceFact(
        "mark-recovery",
        INSTRUMENT,
        OnlyReferencePriceKind.MARK,
        OnlyPrice(Decimal("100.00"), 2),
        NOW,
        NOW,
        "fixture",
        1,
        "v1",
    )
    funding = OnlyFundingRateFact("funding-recovery", INSTRUMENT, Decimal("0.01"), NOW, NOW, "fixture", 2, "v1")
    account_cashflow = OnlyAccountEconomicCashflow(
        "funding-recovery-cash",
        RUNTIME,
        ACCOUNT,
        OnlyAccountEconomicCashflowType.FUNDING,
        OnlyMoney(Decimal("-1.00"), USDT),
        OnlyTimestamp.from_datetime(NOW),
        funding.fact_id,
        str(INSTRUMENT),
    )
    strategy_cashflow = _OnlyStrategyEconomicCashflowApplication(
        OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, CLUSTER, USDT),
        OnlyStrategyCashFlowId("funding-recovery-strategy"),
        OnlyMoney(Decimal("-1.00"), USDT),
        OnlyStrategyCashEntryType.FUNDING,
        OnlyTimestamp.from_datetime(NOW),
    )
    plan = _OnlyEconomicFactApplicationPlan(
        funding.fact_id,
        funding.to_json(),
        "FUNDING",
        (),
        (account_cashflow,),
        (strategy_cashflow,),
    )
    runtime._reference_price_facts[mark.fact_id] = mark  # type: ignore[attr-defined]
    runtime._reference_prices_by_boundary[  # type: ignore[attr-defined]
        (INSTRUMENT, OnlyReferencePriceKind.MARK, OnlyTimestamp.from_datetime(NOW).unix_nanos)
    ] = mark
    runtime._pending_economic_fact_applications[funding.fact_id] = plan  # type: ignore[attr-defined]
    account.apply_economic_cashflow(account_cashflow)
    strategy.failed = True
    checkpoint = runtime._capture_economic_facts_checkpoint()

    restored = _runtime(account=account, strategy=strategy, position=object(), allocation=object())
    restored.config = runtime.config  # type: ignore[attr-defined]
    restored._restore_economic_facts_checkpoint(checkpoint)
    restored._begin_direct_execution_events = MethodType(lambda _self: None, restored)  # type: ignore[attr-defined]
    restored._complete_direct_execution_events = MethodType(  # type: ignore[attr-defined]
        lambda _self, _succeeded: None,
        restored,
    )
    restored._flush_direct_execution_events = MethodType(lambda _self: None, restored)  # type: ignore[attr-defined]

    restored._resume_pending_economic_fact_applications()

    assert restored._pending_economic_fact_applications == {}  # type: ignore[attr-defined]
    assert restored._funding_rate_facts == {funding.fact_id: funding}  # type: ignore[attr-defined]
    assert account.effects == 1
    assert strategy.applied == {OnlyStrategyCashFlowId("funding-recovery-strategy")}


def test_failed_economic_fact_flushes_events_from_completed_partial_authorities() -> None:
    runtime = _runtime(account=object(), strategy=object(), position=object(), allocation=object())
    fact = OnlyReferencePriceFact(
        "event-flush",
        INSTRUMENT,
        OnlyReferencePriceKind.SETTLEMENT,
        OnlyPrice(Decimal("101.00"), 2),
        NOW,
        NOW,
        "fixture",
        3,
        "v1",
    )
    calls: list[str] = []
    runtime._begin_direct_execution_events = MethodType(lambda _self: calls.append("begin"), runtime)  # type: ignore[attr-defined]
    runtime._flush_direct_execution_events = MethodType(lambda _self: calls.append("flush"), runtime)  # type: ignore[attr-defined]
    runtime._install_reference_price = MethodType(  # type: ignore[attr-defined]
        lambda _self, _fact, *, apply_valuation: (_ for _ in ()).throw(RuntimeError("injected")),
        runtime,
    )

    with pytest.raises(RuntimeError, match="injected"):
        runtime._apply_canonical_economic_fact(SimpleNamespace(payload=OnlyReferencePriceUpdate(fact)))

    assert calls == ["begin", "flush"]


def test_multiple_pending_facts_resume_in_canonical_source_order() -> None:
    runtime = _runtime(account=object(), strategy=object(), position=object(), allocation=object())
    later = OnlyFundingRateFact("a-later", INSTRUMENT, Decimal("0.01"), NOW, NOW, "fixture", 2, "v1")
    earlier = OnlyFundingRateFact("z-earlier", INSTRUMENT, Decimal("0.01"), NOW, NOW, "fixture", 1, "v1")
    for fact in (later, earlier):
        runtime._pending_economic_fact_applications[fact.fact_id] = _OnlyEconomicFactApplicationPlan(  # type: ignore[attr-defined]
            fact.fact_id,
            fact.to_json(),
            "FUNDING",
            (),
            (),
            (),
        )
    applied: list[str] = []

    def apply(_self, fact: OnlyFundingRateFact) -> None:  # type: ignore[no-untyped-def]
        applied.append(fact.fact_id)
        runtime._pending_economic_fact_applications.pop(fact.fact_id)  # type: ignore[attr-defined]

    runtime._apply_funding_rate = MethodType(apply, runtime)  # type: ignore[attr-defined]
    runtime._begin_direct_execution_events = MethodType(lambda _self: None, runtime)  # type: ignore[attr-defined]
    runtime._complete_direct_execution_events = MethodType(  # type: ignore[attr-defined]
        lambda _self, _succeeded: None,
        runtime,
    )
    runtime._flush_direct_execution_events = MethodType(lambda _self: None, runtime)  # type: ignore[attr-defined]

    runtime._resume_pending_economic_fact_applications()

    assert applied == ["z-earlier", "a-later"]


def test_settlement_retry_completes_before_reference_fact_registration() -> None:
    position = _IdempotentPosition()
    allocation = _FailOnceAllocation()
    runtime = _runtime(
        account=_IdempotentAccount(),
        strategy=_FailOnceStrategy(),
        position=position,
        allocation=allocation,
    )
    policy = SimpleNamespace(
        variation_margin_policy=object(),
        economic_model=OnlyEconomicModel.MARGINED_DERIVATIVE,
        valuation_policy=None,
    )
    runtime.config = SimpleNamespace(  # type: ignore[attr-defined]
        market_rule_engine=SimpleNamespace(compiled_rules=lambda *_args, **_kwargs: policy)
    )
    fact = OnlyReferencePriceFact(
        "settlement",
        INSTRUMENT,
        OnlyReferencePriceKind.SETTLEMENT,
        OnlyPrice(Decimal("101.00"), 2),
        NOW,
        NOW,
        "fixture",
        3,
        "v1",
    )
    settlement = OnlyPositionSettlementFact(
        OnlyPositionKey(RUNTIME, ACCOUNT, INSTRUMENT),
        fact,
        OnlyMultiplier(Decimal("1"), 0),
        USDT,
    )
    plan = _OnlyEconomicFactApplicationPlan(fact.fact_id, fact.to_json(), "SETTLEMENT", (settlement,), (), ())
    runtime._plan_settlement_application = MethodType(lambda _self, _fact: plan, runtime)  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="injected allocation failure"):
        runtime._install_reference_price(fact, apply_valuation=True)
    assert fact.fact_id not in runtime._reference_price_facts  # type: ignore[attr-defined]
    assert position.effects == 1

    runtime._install_reference_price(fact, apply_valuation=True)
    assert runtime._reference_price_facts[fact.fact_id] == fact  # type: ignore[attr-defined]
    assert position.effects == 1
    assert allocation.effects == 1


def test_economic_fact_checkpoint_restores_pending_plan_and_reference_index() -> None:
    runtime = _runtime(account=object(), strategy=object(), position=object(), allocation=object())
    mark = OnlyReferencePriceFact(
        "mark-checkpoint",
        INSTRUMENT,
        OnlyReferencePriceKind.MARK,
        OnlyPrice(Decimal("100.00"), 2),
        NOW,
        NOW,
        "fixture",
        1,
        "v1",
    )
    funding = OnlyFundingRateFact(
        "funding-checkpoint",
        INSTRUMENT,
        Decimal("0.01"),
        NOW,
        NOW,
        "fixture",
        2,
        "v1",
    )
    plan = _OnlyEconomicFactApplicationPlan(funding.fact_id, funding.to_json(), "FUNDING", (), (), ())
    runtime._reference_price_facts[mark.fact_id] = mark  # type: ignore[attr-defined]
    runtime._funding_rate_facts[funding.fact_id] = funding  # type: ignore[attr-defined]
    runtime._pending_economic_fact_applications[funding.fact_id] = plan  # type: ignore[attr-defined]

    checkpoint = runtime._capture_economic_facts_checkpoint()
    restored = _runtime(account=object(), strategy=object(), position=object(), allocation=object())
    restored._restore_economic_facts_checkpoint(checkpoint)

    boundary = (
        INSTRUMENT,
        OnlyReferencePriceKind.MARK,
        OnlyTimestamp.from_datetime(NOW).unix_nanos,
    )
    assert restored._reference_prices_by_boundary[boundary] == mark  # type: ignore[attr-defined]
    assert restored._funding_rate_facts == {funding.fact_id: funding}  # type: ignore[attr-defined]
    assert restored._pending_economic_fact_applications == {funding.fact_id: plan}  # type: ignore[attr-defined]
