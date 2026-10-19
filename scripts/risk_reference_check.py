"""Actual Python Risk Pipeline/Reservation against independent common literals."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
from onlyalpha.risk.enums import OnlyRiskReleaseReason, OnlyRiskRuleMode
from onlyalpha.risk.pipeline import OnlyRiskPipeline
from onlyalpha.risk.reservations import OnlyRiskReservationManager
from onlyalpha.risk.rules.runtime import OnlyMaxOrderQuantityRiskRule

ROOT = Path(__file__).resolve().parents[1]


def reference_outputs() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for line in (ROOT / "test-data/risk/decisions-v1.jsonl").read_text().splitlines():
        c = json.loads(line)
        request = OnlyOrderRequest(
            OnlyOrderRequestId(c["case"]),
            OnlyInstrumentId.parse("BTCUSDT.BINANCE"),
            OnlyOrderSide.BUY,
            OnlyOrderType.MARKET,
            OnlyQuantity(Decimal(c["quantity"]), 0),
        )
        rule = OnlyMaxOrderQuantityRiskRule(OnlyQuantity(Decimal(c["limit"]), 0), mode=OnlyRiskRuleMode(c["mode"]))
        # This real rule reads only Request quantity; None is not a mocked context.
        d = OnlyRiskPipeline((rule,)).evaluate(request, None).decision  # type: ignore[arg-type]
        actual = {"case": c["case"], "outcome": d.outcome.value, "observations": len(d.observations)}
        if actual != {k: c[k] for k in ("case", "outcome", "observations")}:
            raise ValueError("RISK_PYTHON_DECISION_LITERAL_CONFLICT")
        result.append(actual)
    runtime, cluster, account = OnlyRuntimeId("r"), OnlyClusterId("c1"), OnlyAccountId("a")
    currency = OnlyCurrency("USD", 2)

    def amount(value: str) -> OnlyMoney:
        return OnlyMoney(Decimal(value), currency)

    def money_text(value: Decimal) -> str:
        canonical = format(value, ".2f")
        if Decimal(canonical) != value:
            raise ValueError("RISK_REFERENCE_PRECISION_LOSS")
        return canonical

    for line in (ROOT / "test-data/risk/reservations-v1.jsonl").read_text().splitlines():
        c = json.loads(line)
        m = OnlyRiskReservationManager(runtime)
        order = OnlyOrderId("o1")
        m.create(
            cluster,
            account,
            order,
            OnlyInstrumentId.parse("BTCUSDT.BINANCE"),
            amount("100"),
            OnlyQuantity(Decimal(10), 0),
            OnlyTimestamp(1),
        )
        for n, f in enumerate(c["fills"], 2):
            m.consume_fill_for_order(
                order,
                OnlyQuantity(Decimal(f["quantity"]), 0),
                amount(f["notional"]),
                OnlyTimestamp(n),
                runtime_id=runtime,
                cluster_id=cluster,
                complete=f["complete"],
            )
        if c["release"]:
            m.release_for_order(
                order, OnlyRiskReleaseReason.ORDER_CANCELLED, OnlyTimestamp(10), runtime_id=runtime, cluster_id=cluster
            )
        h = m.get_for_order(order)
        assert (
            h is not None
            and h.consumed_quantity is not None
            and h.consumed_notional is not None
            and h.released_quantity is not None
            and h.released_notional is not None
        )
        actual = {
            "state": h.state.value,
            "consumed_quantity": str(h.consumed_quantity.value),
            "consumed_notional": money_text(h.consumed_notional.amount),
            "released_quantity": str(h.released_quantity.value),
            "released_notional": money_text(h.released_notional.amount),
        }
        if actual != c["expected"]:
            raise ValueError(f"RISK_PYTHON_RESERVATION_LITERAL_CONFLICT:{actual}")
        result.append({"case": c["case"], **actual})
    return result


def compare_native_outputs(native: list[dict[str, object]]) -> None:
    if native != reference_outputs():
        raise ValueError("RISK_PYTHON_RUST_CONFLICT")
