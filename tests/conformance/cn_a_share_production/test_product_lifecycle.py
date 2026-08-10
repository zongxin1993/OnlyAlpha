from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderStatus
from onlyalpha.execution.accepted_fact import OnlyCommittedOrderAcceptedFact
from onlyalpha.execution.committed import OnlyCommittedExecutionFact
from onlyalpha.execution.terminal_fact import OnlyCommittedTerminalExecutionFact
from onlyalpha.fee.models import OnlyFeeType
from onlyalpha.settlement.facts import OnlyCommittedSettlementMaturityFact
from tests.conformance.cn_a_share_production.support import (
    BROKER_FEE_CONTRACT_ID,
    BROKER_FEE_CONTRACT_VERSION,
    MARKET_FEE_PACK_ID,
    MARKET_FEE_PACK_VERSION,
    MARKET_PROFILE_ID,
    MARKET_PROFILE_VERSION,
    PRODUCT_CONTRACT_VERSION,
    PRODUCT_ID,
    OnlyCnAshareProductRun,
    OnlyCnAshareProductScenario,
    only_cn_a_share_product_config,
    only_cn_a_share_product_transactions,
    only_run_cn_a_share_product,
)

pytestmark = pytest.mark.conformance


def _run(
    tmp_path: Path,
    name: str,
    *,
    instrument_id: str = "600000.XSHG",
    scenario: OnlyCnAshareProductScenario = OnlyCnAshareProductScenario.ROUND_TRIP,
    multi_fill: bool = False,
    simulation_submissions: tuple[Mapping[str, object], ...] = (),
) -> OnlyCnAshareProductRun:
    run = only_run_cn_a_share_product(
        tmp_path / name,
        engine_id=f"p43-{name}",
        config=only_cn_a_share_product_config(
            instrument_id=instrument_id,
            scenario=scenario,
            multi_fill=multi_fill,
            simulation_submissions=simulation_submissions,
        ),
    )
    assert run.engine_result.status == "COMPLETED", run.engine_result.failures
    assert run.runtime_result.reconciliation.status == "MATCHED"
    return run


def _strategy_extension(run: OnlyCnAshareProductRun) -> Mapping[str, object]:
    extension = run.runtime_result.cluster_results[0].strategy_result_extension
    assert extension["product_id"] == PRODUCT_ID
    assert extension["product_contract_version"] == PRODUCT_CONTRACT_VERSION
    return extension


def _submission(extension: Mapping[str, object], tag: str) -> Mapping[str, object]:
    rows = extension["submission_results"]
    assert isinstance(rows, list)
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("tag") == tag]
    assert len(matches) == 1
    return matches[0]


def _fee_components(fact: OnlyCommittedExecutionFact) -> dict[OnlyFeeType, Decimal]:
    return {item.identity.fee_type: item.amount.amount for item in fact.fee_application.components}


@pytest.mark.parametrize(
    ("instrument_id", "venue_schedule"),
    (
        ("600000.XSHG", "SSE"),
        ("000001.XSHE", "SZSE"),
    ),
)
def test_production_round_trip_uses_canonical_authorities_and_t_plus_one(
    tmp_path: Path,
    instrument_id: str,
    venue_schedule: str,
) -> None:
    run = _run(tmp_path, venue_schedule.lower(), instrument_id=instrument_id)
    result = run.runtime_result
    transactions = only_cn_a_share_product_transactions(run)
    facts = tuple(item.fact for item in transactions)
    accepted = tuple(item for item in facts if isinstance(item, OnlyCommittedOrderAcceptedFact))
    fills = tuple(item for item in facts if isinstance(item, OnlyCommittedExecutionFact))
    maturities = tuple(item for item in facts if isinstance(item, OnlyCommittedSettlementMaturityFact))

    assert len(result.orders) == 2
    assert len(accepted) == 2
    assert len(fills) == 2
    assert len(maturities) == 1
    assert [item.order_side for item in fills] == [OnlyOrderSide.BUY, OnlyOrderSide.SELL]
    assert [item.execution_sequence for item in transactions] == list(range(1, len(transactions) + 1))

    extension = _strategy_extension(run)
    rejected = _submission(extension, "PRODUCT_SAME_DAY_SELL")
    assert rejected["created"] is False
    assert rejected["submitted"] is False
    assert rejected["market_reason_code"] == "SELL_QUANTITY_EXCEEDS_AVAILABLE"
    assert rejected["market_rule_code"] == "SELLABLE_POSITION"
    assert rejected["market_profile_id"] == MARKET_PROFILE_ID
    assert rejected["market_profile_version"] == MARKET_PROFILE_VERSION
    assert rejected["market_reference_fingerprint"]
    assert rejected["market_compiled_rule_fingerprint"]

    buy, sell = fills
    for fact in fills:
        assert fact.market_fee_pack_id == MARKET_FEE_PACK_ID
        assert fact.market_fee_pack_version == MARKET_FEE_PACK_VERSION
        assert fact.market_fee_pack_fingerprint
        assert fact.broker_fee_contract_id == BROKER_FEE_CONTRACT_ID
        assert fact.broker_fee_contract_version == BROKER_FEE_CONTRACT_VERSION
        assert fact.broker_fee_contract_fingerprint
        assert fact.market_profile_id == MARKET_PROFILE_ID
        assert fact.market_profile_version == MARKET_PROFILE_VERSION
        assert fact.reference_fingerprint
        assert fact.compiled_rule_fingerprint

    assert _fee_components(buy) == {
        OnlyFeeType.BROKER_COMMISSION: Decimal("5.00"),
        OnlyFeeType.TRANSFER_FEE: Decimal("0.10"),
    }
    assert _fee_components(sell) == {
        OnlyFeeType.BROKER_COMMISSION: Decimal("5.00"),
        OnlyFeeType.STAMP_DUTY: Decimal("5.10"),
        OnlyFeeType.TRANSFER_FEE: Decimal("0.10"),
    }
    assert all(venue_schedule in item.identity.schedule_id for item in buy.fee_application.components[1:])
    assert all(venue_schedule in item.identity.schedule_id for item in sell.fee_application.components[1:])
    assert buy.position_quantity_before == Decimal("0")
    assert buy.position_quantity_after == Decimal("1000")
    assert sell.position_quantity_before == Decimal("1000")
    assert sell.position_quantity_after == Decimal("0")
    assert sell.released_open_price_quantity == Decimal("10000.00")
    assert sell.realized_pnl_delta.amount == Decimal("200.00")
    assert maturities[0].asset_available_delta.value == Decimal("1000")
    assert result.final_positions == ()
    assert result.final_allocations == ()
    assert result.final_account.realized_pnl.amount == Decimal("200.00")
    assert result.final_account.fees.amount == Decimal("15.30")
    assert result.final_ledgers[0].pnl.realized_pnl == result.final_account.realized_pnl
    assert result.final_ledgers[0].pnl.fees == result.final_account.fees


def test_multi_fill_applies_incremental_fees_and_minimum_commission_once_per_order(tmp_path: Path) -> None:
    run = _run(tmp_path, "multi-fill", multi_fill=True)
    fills = tuple(
        item.fact
        for item in only_cn_a_share_product_transactions(run)
        if isinstance(item.fact, OnlyCommittedExecutionFact)
    )
    assert len(fills) == 6
    assert [item.fill_index for item in fills] == [1, 2, 3, 1, 2, 3]
    assert [item.fill_quantity.value for item in fills] == [
        Decimal("300"),
        Decimal("400"),
        Decimal("300"),
        Decimal("300"),
        Decimal("400"),
        Decimal("300"),
    ]

    for side in (OnlyOrderSide.BUY, OnlyOrderSide.SELL):
        side_fills = tuple(item for item in fills if item.order_side is side)
        commission = tuple(
            next(
                component
                for component in item.fee_application.components
                if component.identity.fee_type is OnlyFeeType.BROKER_COMMISSION
            )
            for item in side_fills
        )
        assert [item.amount.amount for item in commission] == [Decimal("5.00"), Decimal("0.00"), Decimal("0.00")]
        assert [item.cumulative_applied_after.amount for item in commission] == [
            Decimal("5.00"),
            Decimal("5.00"),
            Decimal("5.00"),
        ]
        assert side_fills[-1].order_cumulative_fee_charges_after.amount == (
            Decimal("5.10") if side is OnlyOrderSide.BUY else Decimal("10.20")
        )

    assert [item.position_quantity_after for item in fills] == [
        Decimal("300"),
        Decimal("700"),
        Decimal("1000"),
        Decimal("700"),
        Decimal("300"),
        Decimal("0"),
    ]
    assert run.runtime_result.final_account.fees.amount == Decimal("15.30")
    assert run.runtime_result.final_positions == ()
    assert run.runtime_result.final_allocations == ()


@pytest.mark.parametrize(
    ("name", "action", "expected_status", "accepted_count"),
    (
        ("reject", "REJECT_BEFORE_ACCEPTED", OnlyOrderStatus.REJECTED, 0),
        ("expire", "ACCEPT_THEN_EXPIRE", OnlyOrderStatus.EXPIRED, 1),
    ),
)
def test_broker_reject_and_expire_are_durable_terminal_facts(
    tmp_path: Path,
    name: str,
    action: str,
    expected_status: OnlyOrderStatus,
    accepted_count: int,
) -> None:
    run = _run(
        tmp_path,
        name,
        scenario=OnlyCnAshareProductScenario.BUY_ONLY,
        simulation_submissions=({"submission_index": 1, "action": action},),
    )
    transactions = only_cn_a_share_product_transactions(run)
    accepted = tuple(item.fact for item in transactions if isinstance(item.fact, OnlyCommittedOrderAcceptedFact))
    terminals = tuple(item.fact for item in transactions if isinstance(item.fact, OnlyCommittedTerminalExecutionFact))

    assert len(accepted) == accepted_count
    assert len(terminals) == 1
    assert terminals[0].terminal_status is expected_status
    assert terminals[0].filled_quantity_before.value == Decimal("0")
    assert terminals[0].order_remaining_quantity.value == Decimal("1000")
    assert terminals[0].reservation_released_cash is not None
    assert terminals[0].reservation_released_cash.amount == Decimal("10005.10")
    assert terminals[0].risk_released_quantity.value == Decimal("1000")
    assert run.runtime_result.orders[0].status is expected_status
    assert run.runtime_result.trades == ()
    assert run.runtime_result.final_positions == ()
    assert run.runtime_result.final_allocations == ()
    assert run.runtime_result.final_account.cash.order_reserved_cash.amount == Decimal("0.00")
    assert run.runtime_result.final_account.cash.ledger_cash.amount == Decimal("1000000.00")
    assert run.runtime_result.final_account.fees.amount == Decimal("0")


def test_sell_reject_before_accepted_preserves_settled_position_and_releases_reservation(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        "sell-reject",
        scenario=OnlyCnAshareProductScenario.SELL_AFTER_SETTLEMENT,
        simulation_submissions=({"submission_index": 2, "action": "REJECT_BEFORE_ACCEPTED"},),
    )
    transactions = only_cn_a_share_product_transactions(run)
    accepted = tuple(item.fact for item in transactions if isinstance(item.fact, OnlyCommittedOrderAcceptedFact))
    terminals = tuple(item.fact for item in transactions if isinstance(item.fact, OnlyCommittedTerminalExecutionFact))

    assert [item.status for item in run.runtime_result.orders] == [OnlyOrderStatus.FILLED, OnlyOrderStatus.REJECTED]
    assert len(accepted) == 1
    assert len(terminals) == 1
    assert terminals[0].order_id == run.runtime_result.orders[1].order_id
    assert terminals[0].terminal_status is OnlyOrderStatus.REJECTED
    assert terminals[0].reservation_released_quantity is not None
    assert terminals[0].reservation_released_quantity.value == Decimal("1000")
    assert terminals[0].reservation_released_cash is None
    assert terminals[0].risk_released_quantity.value == Decimal("1000")
    assert len(run.runtime_result.trades) == 1
    assert run.runtime_result.trades[0].order_side is OnlyOrderSide.BUY
    assert run.runtime_result.final_positions[0].total_quantity.value == Decimal("1000")
    assert run.runtime_result.final_positions[0].available_quantity.value == Decimal("1000")
    assert run.runtime_result.final_allocations[0].total_quantity.value == Decimal("1000")
    assert run.runtime_result.final_allocations[0].available_quantity.value == Decimal("1000")
    assert run.runtime_result.final_account.cash.order_reserved_cash.amount == Decimal("0.00")
    assert run.runtime_result.final_account.fees.amount == Decimal("5.10")


@pytest.mark.parametrize(
    ("scenario", "expected_side", "expected_position"),
    (
        (OnlyCnAshareProductScenario.BUY_PARTIAL_CANCEL, OnlyOrderSide.BUY, Decimal("300")),
        (OnlyCnAshareProductScenario.SELL_PARTIAL_CANCEL, OnlyOrderSide.SELL, Decimal("700")),
    ),
)
def test_partial_fill_cancel_preserves_fill_and_releases_only_remaining_reservation(
    tmp_path: Path,
    scenario: OnlyCnAshareProductScenario,
    expected_side: OnlyOrderSide,
    expected_position: Decimal,
) -> None:
    run = _run(tmp_path, scenario.value.lower(), scenario=scenario, multi_fill=True)
    terminal = next(
        item.fact
        for item in only_cn_a_share_product_transactions(run)
        if isinstance(item.fact, OnlyCommittedTerminalExecutionFact)
    )
    cancelled = next(item for item in run.runtime_result.orders if item.status is OnlyOrderStatus.CANCELLED)

    assert cancelled.side is expected_side
    assert cancelled.filled_quantity.value == Decimal("300")
    assert cancelled.remaining_quantity.value == Decimal("700")
    assert terminal.terminal_status is OnlyOrderStatus.CANCELLED
    assert terminal.filled_quantity_before.value == Decimal("300")
    assert terminal.order_remaining_quantity.value == Decimal("700")
    assert terminal.risk_released_quantity.value == Decimal("700")
    assert len(run.runtime_result.trades) == (1 if expected_side is OnlyOrderSide.BUY else 4)
    assert run.runtime_result.final_positions[0].total_quantity.value == expected_position
    assert run.runtime_result.final_allocations[0].total_quantity.value == expected_position
    assert run.runtime_result.final_account.cash.order_reserved_cash.amount == Decimal("0.00")
    assert run.runtime_result.reconciliation.status == "MATCHED"
