from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.execution import (
    OnlyExecutionProjectionComponent,
    only_execution_state_hash,
    only_expected_execution_reservations,
    only_with_execution_projection_hash,
)
from onlyalpha.market.models import OnlyPositionEffect
from tests.execution.factories.transaction_factory import (
    only_test_execution_preconditions,
    only_test_generic_t0_cash_buy_open_transaction,
    only_test_projection_codec_cases,
)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"fill_quantity": OnlyQuantity(Decimal("1"), 0)}, "Order projection"),
        ({"fill_price": OnlyPrice(Decimal("11.00"), 2)}, "Order projection"),
        ({"cumulative_filled_quantity": OnlyQuantity(Decimal("1"), 0)}, "Order projection"),
        ({"position_quantity_delta": Decimal("1")}, "Position projection quantity"),
        ({"allocation_quantity_delta": Decimal("1")}, "Allocation projection quantity"),
        ({"cluster_id": OnlyClusterId("other-cluster")}, "scope"),
    ),
)
def test_prepared_transaction_rejects_cross_projection_economic_contradictions(
    changes: dict[str, object], message: str
) -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    fact = replace(prepared.fact_draft, **changes)
    with pytest.raises(ValueError, match=message):
        replace(prepared, fact_draft=fact, authority_hash="", payload_hash="")


def test_prepared_transaction_rejects_account_ledger_pnl_and_reservation_contradictions() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    currency = prepared.fact_draft.currency
    changes = (
        {"account_cash_delta": OnlyMoney(Decimal("-19.00"), currency)},
        {"ledger_cash_delta": OnlyMoney(Decimal("-19.00"), currency)},
        {"realized_pnl_delta": OnlyMoney(Decimal("1.00"), currency)},
        {"cash_delta": OnlyMoney(Decimal("-19.00"), currency)},
    )
    for change in changes:
        fact = replace(prepared.fact_draft, **change)
        with pytest.raises(ValueError):
            replace(prepared, fact_draft=fact, authority_hash="", payload_hash="")


def test_prepared_transaction_rejects_margin_presence_contradiction() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    margin = next(item for item in only_test_projection_codec_cases() if item.identity.component.value == "MARGIN")
    projections = (*prepared.projections[:4], margin, *prepared.projections[4:])
    projections = tuple(
        only_with_execution_projection_hash(
            replace(item, identity=replace(item.identity, projection_sequence=index, payload_hash="0" * 64))
        )
        for index, item in enumerate(projections, start=1)
    )
    with pytest.raises(ValueError, match="without Margin instruction"):
        replace(
            prepared,
            projections=projections,
            preconditions=only_test_execution_preconditions(projections),
            authority_hash="",
            payload_hash="",
        )


def test_reservation_presence_matrix_is_directional_and_risk_is_mandatory() -> None:
    buy = only_expected_execution_reservations(
        market_profile_id="GENERIC_T0_CASH",
        side=OnlyOrderSide.BUY,
        offset=OnlyOffset.OPEN,
        position_effect=OnlyPositionEffect.OPEN,
        margin_instruction_present=False,
    )
    assert buy.require_account_cash and buy.require_strategy_cash and buy.require_risk
    assert not buy.require_position and not buy.require_margin
    sell = only_expected_execution_reservations(
        market_profile_id="GENERIC_T0_CASH",
        side=OnlyOrderSide.SELL,
        offset=OnlyOffset.CLOSE,
        position_effect=OnlyPositionEffect.CLOSE,
        margin_instruction_present=False,
    )
    assert sell.require_position and sell.require_risk
    assert not sell.require_account_cash and not sell.require_strategy_cash and not sell.require_margin


@pytest.mark.parametrize(
    "component",
    (
        OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION,
        OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION,
        OnlyExecutionProjectionComponent.RISK_RESERVATION,
    ),
)
def test_buy_open_rejects_missing_required_reservation(component: OnlyExecutionProjectionComponent) -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    projections = tuple(item for item in prepared.projections if item.identity.component is not component)
    projections = tuple(
        only_with_execution_projection_hash(
            replace(item, identity=replace(item.identity, projection_sequence=index, payload_hash="0" * 64))
        )
        for index, item in enumerate(projections, start=1)
    )
    with pytest.raises(ValueError, match="requires exactly 1"):
        replace(
            prepared,
            projections=projections,
            preconditions=only_test_execution_preconditions(projections),
            authority_hash="",
            payload_hash="",
        )


def test_buy_open_rejects_position_reservation() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    position_reservation = next(
        item
        for item in only_test_projection_codec_cases()
        if item.identity.component is OnlyExecutionProjectionComponent.POSITION_RESERVATION
    )
    projections = (*prepared.projections[:9], position_reservation, *prepared.projections[9:])
    projections = tuple(
        only_with_execution_projection_hash(
            replace(item, identity=replace(item.identity, projection_sequence=index, payload_hash="0" * 64))
        )
        for index, item in enumerate(projections, start=1)
    )
    with pytest.raises(ValueError, match="requires exactly 0"):
        replace(
            prepared,
            projections=projections,
            preconditions=only_test_execution_preconditions(projections),
            authority_hash="",
            payload_hash="",
        )


@pytest.mark.parametrize(
    ("component", "field", "value"),
    (
        (OnlyExecutionProjectionComponent.FEE, "account_id", "other-account"),
        (OnlyExecutionProjectionComponent.FEE, "order_id", "other-order"),
        (OnlyExecutionProjectionComponent.FEE, "trade_id", "other-trade"),
        (OnlyExecutionProjectionComponent.SETTLEMENT, "account_id", OnlyAccountId("other-account")),
        (
            OnlyExecutionProjectionComponent.RISK,
            "instrument_id",
            OnlyInstrumentId(OnlySymbol("OTHER"), OnlyVenueId("XSHG")),
        ),
    ),
)
def test_prepared_transaction_rejects_fee_settlement_and_risk_scope_corruption(
    component: OnlyExecutionProjectionComponent, field: str, value: object
) -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    projections = list(prepared.projections)
    index = next(index for index, item in enumerate(projections) if item.identity.component is component)
    projection = projections[index]
    if component is OnlyExecutionProjectionComponent.FEE:
        after = replace(projection.after, instruction=replace(projection.after.instruction, **{field: value}))
    else:
        after = replace(projection.after, **{field: value})
    identity = replace(
        projection.identity,
        result_state_hash=only_execution_state_hash(after),
        payload_hash="0" * 64,
    )
    projections[index] = only_with_execution_projection_hash(replace(projection, identity=identity, after=after))
    projected = tuple(projections)
    with pytest.raises(ValueError, match="scope|contradicts"):
        replace(
            prepared,
            projections=projected,
            preconditions=only_test_execution_preconditions(projected),
            authority_hash="",
            payload_hash="",
        )
