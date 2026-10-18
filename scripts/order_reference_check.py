"""Deterministic Order fixtures and valid Python comparison; never Runtime admission."""

from __future__ import annotations

# ruff: noqa: E402
import json
import sys
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRequest, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueOrderId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from tests.order.fee_contract import only_test_zero_fee_contract


def _manager() -> OnlyOrderManager:
    runtime = OnlyRuntimeId("runtime")
    return OnlyOrderManager(
        OnlyEngineId("engine"),
        runtime,
        OnlySequenceOrderIdGenerator(runtime),
        OnlySequenceClientOrderIdGenerator(runtime),
    )


def _request(request_id: str = "request-1") -> OnlyOrderRequest:
    return OnlyOrderRequest(
        OnlyOrderRequestId(request_id),
        OnlyInstrumentId.parse("600000.XSHG"),
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("4"), 0),
        price=OnlyPrice(Decimal("10.00"), 2),
    )


def domain_fixture() -> dict[str, object]:
    manager = _manager()
    request = _request()
    first = manager.create_order(request, OnlyClusterId("cluster"), OnlyAccountId("account"), OnlyTimestamp(1))
    second = manager.create_order(
        _request("request-2"), OnlyClusterId("cluster"), OnlyAccountId("account"), OnlyTimestamp(1)
    )

    def contract(snapshot: OnlyOrderSnapshot) -> dict[str, object]:
        return dict(
            zip(
                ("binding", "estimate", "funding"),
                (part.to_dict() for part in only_test_zero_fee_contract(snapshot, OnlyTimestamp(1))),
                strict=True,
            )
        )

    return {
        "request": request.to_dict(),
        "fee_contract": contract(first.snapshot),
        "second_fee_contract": contract(second.snapshot),
    }


def check_fixture() -> None:
    expected = json.dumps(domain_fixture(), sort_keys=True, separators=(",", ":")) + "\n"
    assert (ROOT / "test-data/order/domain-inputs.json").read_text() == expected


def reference_outputs() -> list[dict[str, object]]:
    outputs: list[dict[str, object]] = []
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        for line in (ROOT / "test-data/order/lifecycle-v1.jsonl").read_text().splitlines():
            case = json.loads(line)
            manager = _manager()
            created = manager.create_order(
                _request(),
                OnlyClusterId("cluster"),
                OnlyAccountId("account"),
                OnlyTimestamp(1),
                fee_contract_factory=only_test_zero_fee_contract,
            )
            order_id = created.order_id
            manager.mark_submitted(order_id, OnlyTimestamp(2))
            observed = []
            for index, (price, quantity) in enumerate(case["fills"], 1):
                timestamp = OnlyTimestamp(index + 3)
                fill = OnlyOrderFill(
                    OnlyTradeId(f"trade-{index}"),
                    order_id,
                    OnlyPrice(Decimal(price), 2),
                    OnlyQuantity(Decimal(quantity), 0),
                    timestamp,
                    timestamp,
                    venue_trade_id=OnlyVenueTradeId(f"venue-trade-{index}"),
                    venue_order_id=OnlyVenueOrderId("venue-1"),
                    external_sequence=index,
                    external_event_id=f"event-{index}",
                )
                result = manager.apply_fill(fill)
                assert result.changed
                snapshot = result.snapshot
                assert snapshot.average_fill_price is not None
                observed.append(
                    [
                        snapshot.status.value,
                        str(snapshot.filled_quantity.value),
                        str(snapshot.average_fill_price.value),
                        str(snapshot.cumulative_price_quantity),
                    ]
                )
                fresh = _manager()
                fresh.restore_checkpoint(manager.capture_checkpoint())
                assert fresh.capture_checkpoint() == manager.capture_checkpoint()
                manager = fresh
            assert observed == case["expected"], (case["case"], observed)
            outputs.append({"case": case["case"], "observed": observed})
    return outputs


def compare_native_outputs(observed: list[dict[str, object]]) -> None:
    assert observed == reference_outputs(), "ORDER_NATIVE_PYTHON_MISMATCH"


if __name__ == "__main__":
    if sys.argv[1:] == ["write-fixture"]:
        (ROOT / "test-data/order/domain-inputs.json").write_text(
            json.dumps(domain_fixture(), sort_keys=True, separators=(",", ":")) + "\n"
        )
    else:
        check_fixture()
        print(json.dumps(reference_outputs(), sort_keys=True))
