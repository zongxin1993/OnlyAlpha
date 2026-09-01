from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.execution import OnlyExecutionCapability
from tests.execution.factories.transaction_factory import only_test_execution_fact_draft


def test_committed_fact_carries_complete_multi_fill_audit_authority() -> None:
    base = only_test_execution_fact_draft()
    partial = replace(
        base,
        fill_quantity=OnlyQuantity(Decimal("1"), 0),
        gross_notional=replace(base.gross_notional, amount=Decimal("10.00")),
        settled_notional=replace(base.settled_notional, amount=Decimal("10.00")),
        cumulative_filled_quantity=OnlyQuantity(Decimal("1"), 0),
        remaining_quantity=OnlyQuantity(Decimal("1"), 0),
        order_status_after=OnlyOrderStatus.PARTIALLY_FILLED,
        fill_index=1,
        fill_count_after=1,
        terminal_fill=False,
        cumulative_price_quantity_after=Decimal("10.00"),
    ).finalize(1, base.ts_init)
    final = replace(
        base,
        fill_index=2,
        fill_count_after=2,
        terminal_fill=True,
        cumulative_price_quantity_after=Decimal("20.00"),
    ).finalize(2, OnlyTimestamp(base.ts_init.unix_nanos + 1))
    assert partial.fill_identity.startswith("EFILL-")
    assert len(partial.fill_payload_fingerprint) == 64
    assert partial.execution_capability is OnlyExecutionCapability.DURABLE_TRADE
    assert partial.execution_support_policy_version == "3"
    assert len(partial.execution_support_fingerprint) == 64
    assert (partial.fill_index, partial.fill_count_after, partial.terminal_fill) == (1, 1, False)
    assert partial.order_status_after is OnlyOrderStatus.PARTIALLY_FILLED
    assert (final.fill_index, final.fill_count_after, final.terminal_fill) == (2, 2, True)
    assert final.order_status_after is OnlyOrderStatus.FILLED
