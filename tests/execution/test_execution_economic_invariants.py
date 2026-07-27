from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.domain.identifiers import OnlyClusterId
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from tests.execution.factories.transaction_factory import (
    only_test_all_projection_types_transaction,
    only_test_generic_t0_cash_buy_open_transaction,
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
    prepared = only_test_all_projection_types_transaction()
    fact = replace(
        prepared.fact_draft,
        margin_instruction_id=None,
        margin_action=None,
        margin_currency=None,
        margin_amount=None,
        reserved_margin_delta=None,
        occupied_margin_delta=None,
        released_margin_delta=None,
        maintenance_margin_after=None,
    )
    with pytest.raises(ValueError, match="without Margin instruction"):
        replace(prepared, fact_draft=fact, authority_hash="", payload_hash="")
