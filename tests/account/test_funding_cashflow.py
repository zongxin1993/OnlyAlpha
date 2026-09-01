from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.account.enums import OnlyAccountMutationStatus, OnlyAccountType
from onlyalpha.account.funding import only_derive_funding_cashflow
from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountConfig
from onlyalpha.domain.enums import OnlyDirection, OnlyOffset, OnlyOrderSide
from onlyalpha.domain.market import OnlyFundingRateFact, OnlyReferencePriceFact
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyMoney, OnlyMultiplier, OnlyPrice
from onlyalpha.market.economics import OnlyCompiledFundingPolicy
from onlyalpha.position.enums import OnlyPositionSide, OnlySettlementBucket
from onlyalpha.position.manager import OnlyPositionManager
from tests.position.test_position_component import ACCOUNT, CNY, INSTRUMENT, RUNTIME, trade


def _position(side: OnlyPositionSide):
    item = trade(1, OnlyOrderSide.BUY, "2", "100", bucket=OnlySettlementBucket.SETTLED)
    if side is OnlyPositionSide.SHORT:
        item = replace(
            item,
            side=OnlyOrderSide.SELL,
            direction=OnlyDirection.SELL,
            offset=OnlyOffset.OPEN,
            position_side=OnlyPositionSide.SHORT,
        )
    manager = OnlyPositionManager(RUNTIME)
    result = manager.apply_trade(item)
    assert result.after is not None
    return result.after


def _facts():
    timestamp = datetime(2026, 9, 1, tzinfo=UTC)
    funding = OnlyFundingRateFact("funding-1", INSTRUMENT, Decimal("0.01"), timestamp, timestamp, "TEST", 1, "v1")
    mark = OnlyReferencePriceFact(
        "mark-1",
        INSTRUMENT,
        OnlyReferencePriceKind.MARK,
        OnlyPrice(Decimal("100"), 2),
        timestamp,
        timestamp,
        "TEST",
        1,
        "v1",
    )
    return funding, mark


def test_funding_payer_receiver_signs_and_duplicate_idempotency() -> None:
    funding, mark = _facts()
    policy = OnlyCompiledFundingPolicy(8 * 60 * 60, OnlyReferencePriceKind.MARK)
    long_cashflow = only_derive_funding_cashflow(
        runtime_id=RUNTIME,
        account_id=ACCOUNT,
        position=_position(OnlyPositionSide.LONG),
        funding=funding,
        valuation=mark,
        multiplier=OnlyMultiplier(Decimal("1"), 0),
        currency=CNY,
        policy=policy,
    )
    short_cashflow = only_derive_funding_cashflow(
        runtime_id=RUNTIME,
        account_id=ACCOUNT,
        position=_position(OnlyPositionSide.SHORT),
        funding=funding,
        valuation=mark,
        multiplier=OnlyMultiplier(Decimal("1"), 0),
        currency=CNY,
        policy=policy,
    )
    assert long_cashflow.amount.amount == Decimal("-2.00")
    assert short_cashflow.amount.amount == Decimal("2.00")

    accounts = OnlyAccountManager(RUNTIME)
    accounts.create_account(
        OnlyAccountConfig(RUNTIME, ACCOUNT, "TEST", OnlyAccountType.MARGIN, CNY, OnlyMoney(Decimal("100"), CNY)),
        OnlyTimestamp(0),
    )
    applied = accounts.apply_economic_cashflow(long_cashflow)
    duplicate = accounts.apply_economic_cashflow(long_cashflow)
    assert applied.after.cash.ledger_cash.amount == Decimal("98.00")
    assert duplicate.status is OnlyAccountMutationStatus.DUPLICATE

    checkpoint = accounts.capture_checkpoint()
    restored = OnlyAccountManager(RUNTIME)
    restored.create_account(
        OnlyAccountConfig(RUNTIME, ACCOUNT, "TEST", OnlyAccountType.MARGIN, CNY, OnlyMoney(Decimal("100"), CNY)),
        OnlyTimestamp(0),
    )
    restored.restore_checkpoint(checkpoint)
    assert restored.economic_cashflows == accounts.economic_cashflows
    assert restored.require_snapshot(ACCOUNT) == accounts.require_snapshot(ACCOUNT)


def test_funding_requires_compiled_interval_boundary() -> None:
    funding, mark = _facts()
    shifted_time = funding.funding_time.replace(minute=1)
    shifted = replace(funding, funding_time=shifted_time, ts_init=shifted_time)
    shifted_mark = replace(mark, ts_event=shifted.funding_time, ts_init=shifted.funding_time)
    try:
        only_derive_funding_cashflow(
            runtime_id=RUNTIME,
            account_id=ACCOUNT,
            position=_position(OnlyPositionSide.LONG),
            funding=shifted,
            valuation=shifted_mark,
            multiplier=OnlyMultiplier(Decimal("1"), 0),
            currency=CNY,
            policy=OnlyCompiledFundingPolicy(8 * 60 * 60, OnlyReferencePriceKind.MARK),
        )
    except ValueError as exc:
        assert str(exc) == "FUNDING_INTERVAL_BOUNDARY_CONFLICT"
    else:
        raise AssertionError("off-boundary funding must fail closed")


def test_funding_rejects_subsecond_time_after_interval_boundary() -> None:
    funding, mark = _facts()
    shifted_time = funding.funding_time.replace(microsecond=500_000)
    shifted = replace(funding, funding_time=shifted_time, ts_init=shifted_time)
    shifted_mark = replace(mark, ts_event=shifted_time, ts_init=shifted_time)

    try:
        only_derive_funding_cashflow(
            runtime_id=RUNTIME,
            account_id=ACCOUNT,
            position=_position(OnlyPositionSide.LONG),
            funding=shifted,
            valuation=shifted_mark,
            multiplier=OnlyMultiplier(Decimal("1"), 0),
            currency=CNY,
            policy=OnlyCompiledFundingPolicy(8 * 60 * 60, OnlyReferencePriceKind.MARK),
        )
    except ValueError as exc:
        assert str(exc) == "FUNDING_INTERVAL_BOUNDARY_CONFLICT"
    else:
        raise AssertionError("subsecond off-boundary funding must fail closed")
