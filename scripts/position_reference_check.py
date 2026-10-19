"""Actual valid Python Position Opens and canonical Close reducer vs independent vectors."""

from __future__ import annotations

# ruff: noqa: E402
import json
import sys
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from onlyalpha.domain.enums import OnlyDirection, OnlyOffset, OnlyOrderSide
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.execution.reducers.close_cost import only_reduce_average_cost_close
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.enums import OnlyPositionSide, OnlySettlementBucket
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.models import OnlyPositionTrade


def normalized(value: Decimal) -> str:
    # format rather than normalize: ambient Decimal precision must not round a 36-digit cost.
    token = format(value, "f")
    return token.rstrip("0").rstrip(".") if "." in token else token


def reference_outputs() -> list[dict[str, object]]:
    outputs: list[dict[str, object]] = []
    with localcontext(Context(prec=128, rounding=ROUND_HALF_EVEN)):
        for line in (ROOT / "test-data/position/lifecycle-v1.jsonl").read_text().splitlines():
            case = json.loads(line)
            observed: list[list[str]] = []
            if case["case"].startswith("opens"):
                runtime = OnlyRuntimeId("runtime")
                positions = OnlyPositionManager(runtime)
                allocations = OnlyPositionAllocationManager(runtime)
                for index, (price, quantity) in enumerate(case["fills"], 1):
                    trade = OnlyPositionTrade(
                        OnlyTradeId(f"trade-{index}"),
                        None,
                        OnlyOrderId("order-a"),
                        OnlyClusterId("a"),
                        runtime,
                        OnlyAccountId("account"),
                        OnlyInstrumentId.parse("BTCUSDT.BINANCE"),
                        OnlyOrderSide.BUY,
                        OnlyDirection.BUY,
                        OnlyOffset.OPEN,
                        OnlyPositionSide.LONG,
                        OnlyPrice(Decimal(price), 2),
                        OnlyQuantity(Decimal(quantity), 0),
                        OnlyMoney(Decimal("0.00"), OnlyCurrency("USD", 2)),
                        OnlyTimestamp(index),
                        OnlyTimestamp(index),
                        external_sequence=index,
                        settlement_bucket=OnlySettlementBucket.SETTLED,
                    )
                    result = positions.apply_trade(trade)
                    allocations.apply_trade(trade)
                    snapshot = result.after
                    assert snapshot is not None and snapshot.average_open_price is not None
                    allocation = allocations.snapshot_all()[0]
                    assert snapshot.cumulative_open_price_quantity == allocation.cumulative_open_price_quantity
                    observed.append(
                        [
                            normalized(snapshot.total_quantity.value),
                            normalized(snapshot.cumulative_open_price_quantity),
                            str(snapshot.average_open_price.value),
                        ]
                    )
                    fresh_positions = OnlyPositionManager(runtime)
                    fresh_positions.restore_checkpoint(positions.capture_checkpoint())
                    fresh_allocations = OnlyPositionAllocationManager(runtime)
                    fresh_allocations.restore_checkpoint(allocations.capture_checkpoint())
                    assert fresh_positions.capture_checkpoint() == positions.capture_checkpoint()
                    assert fresh_allocations.capture_checkpoint() == allocations.capture_checkpoint()
                    positions, allocations = fresh_positions, fresh_allocations
            else:
                cost, quantity = Decimal(case["cost"]), Decimal(case["quantity"])
                for amount in case["fills"]:
                    reduction = only_reduce_average_cost_close(
                        cumulative_open_price_quantity_before=cost,
                        quantity_before=OnlyQuantity(quantity, 0),
                        fill_quantity=OnlyQuantity(Decimal(amount), 0),
                    )
                    observed.append(
                        [
                            normalized(reduction.released_open_price_quantity),
                            normalized(reduction.cumulative_open_price_quantity_after),
                        ]
                    )
                    cost, quantity = reduction.cumulative_open_price_quantity_after, reduction.quantity_after.value
            assert observed == case["expected"], (case["case"], observed, case["expected"])
            outputs.append({"case": case["case"], "observed": observed})
    return outputs


def compare_native_outputs(observed: list[dict[str, object]]) -> None:
    assert observed == reference_outputs(), "POSITION_NATIVE_PYTHON_MISMATCH"


if __name__ == "__main__":
    print(json.dumps(reference_outputs(), sort_keys=True))
