"""Independent exact-cost vectors and actual Python common Position valuation."""

from __future__ import annotations

import json
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Any


def compare_native(root: Path, outputs: list[dict[str, Any]]) -> None:
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
    from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
    from onlyalpha.position.enums import OnlyPositionSide, OnlySettlementBucket
    from onlyalpha.position.manager import OnlyPositionManager
    from onlyalpha.position.models import OnlyPositionTrade
    from onlyalpha.position.pnl import OnlyPositionValuationService

    if json.loads((root / "test-data/position/valuation-order-contract.json").read_text()) != second_cluster_contract():
        raise ValueError("VALUATION_ORDER_FIXTURE_DRIFT")
    cases = [json.loads(line) for line in (root / "test-data/position/valuation-v1.jsonl").read_text().splitlines()]
    if len(outputs) != len(cases):
        raise ValueError("VALUATION_REFERENCE_CARDINALITY")
    with localcontext() as context:
        context.prec = 128
        context.rounding = ROUND_HALF_EVEN
        for case, output in zip(cases, outputs, strict=True):
            if output != {"case": case["case"], "market": case["market"], "unrealized": case["unrealized"]}:
                raise ValueError("VALUATION_LITERAL_VECTOR_MISMATCH")
            if not case["python_common"]:
                continue  # Rounded-average Python PnL is not the native exact-cost contract.
            runtime = OnlyRuntimeId("runtime")
            currency = OnlyCurrency("USD", 2)
            positions = OnlyPositionManager(runtime)
            snapshot = None
            for n, (cluster, price, quantity) in enumerate(case["trades"], 1):
                trade = OnlyPositionTrade(
                    OnlyTradeId(f"trade-{n}"),
                    None,
                    OnlyOrderId(f"order-{n}"),
                    OnlyClusterId(cluster),
                    runtime,
                    OnlyAccountId("account"),
                    OnlyInstrumentId.parse("BTCUSDT.BINANCE"),
                    OnlyOrderSide.BUY,
                    OnlyDirection.BUY,
                    OnlyOffset.OPEN,
                    OnlyPositionSide.LONG,
                    OnlyPrice(Decimal(price), 8),
                    OnlyQuantity(Decimal(quantity), 8),
                    OnlyMoney(Decimal("0"), currency),
                    OnlyTimestamp(n),
                    OnlyTimestamp(n),
                    external_sequence=n,
                    settlement_bucket=OnlySettlementBucket.SETTLED,
                    multiplier=OnlyMultiplier(Decimal(case["multiplier"]), 8),
                )
                snapshot = positions.apply_trade(trade).after
            assert snapshot is not None
            result = OnlyPositionValuationService().value(
                snapshot,
                OnlyPrice(Decimal(case["mark"]), 8),
                OnlyMultiplier(Decimal(case["multiplier"]), 8),
                currency,
                OnlyTimestamp(100),
                price_source="closed-bar",
            )
            if result.market_value.amount != Decimal(output["market"]) or result.unrealized_pnl.amount != Decimal(
                output["unrealized"]
            ):
                raise ValueError("VALUATION_PYTHON_COMMON_MISMATCH")


def second_cluster_contract() -> dict[str, Any]:
    from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId
    from onlyalpha.domain.time import OnlyTimestamp
    from scripts.order_reference_check import _manager, _request
    from tests.order.fee_contract import only_test_zero_fee_contract

    manager = _manager()
    manager.create_order(_request("request-1"), OnlyClusterId("cluster"), OnlyAccountId("account"), OnlyTimestamp(1))
    second = manager.create_order(
        _request("request-2"), OnlyClusterId("other"), OnlyAccountId("account"), OnlyTimestamp(4)
    )
    return dict(
        zip(
            ("binding", "estimate", "funding"),
            (part.to_dict() for part in only_test_zero_fee_contract(second.snapshot, OnlyTimestamp(4))),
            strict=True,
        )
    )
