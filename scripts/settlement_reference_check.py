"""Actual Python schedule/initial Authority/due comparison plus independent native maturity/restart proof.

Technical controlled facts; component identities and Python schema2 identities are intentionally distinct.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
AXES = (
    "asset_booked",
    "asset_trade_available",
    "cash_booked",
    "cash_trade_available",
    "cash_withdrawable",
    "legal_settled",
)


def cases(root: Path = ROOT) -> list[dict[str, Any]]:
    original = json.loads((root / "test-data/settlement/common-v1.json").read_text())
    result = []
    for label, asset, cash, legal, target, side in (
        ("T0", 0, 0, 0, "2026-10-23", "BUY"),
        ("T1", 1, 1, 1, "2026-10-27", "BUY"),
        ("T2-cash", 1, 1, 2, "2026-10-28", "SELL"),
        ("T3", 3, 2, 3, "2026-10-29", "BUY"),
    ):
        fixture = copy.deepcopy(original)
        fixture["side"] = side
        if side == "SELL":
            fixture["gross_notional"] = "48.00"
        fixture["policy"].update(asset_trade_available=asset, cash_withdrawable=cash, legal_settled=legal)
        dates = {0: "2026-10-23", 1: "2026-10-27", 2: "2026-10-28", 3: "2026-10-29"}
        expected = {key: dates[fixture["policy"][key]] for key in AXES}
        result.append({"label": label, "fixture": fixture, "expected": expected, "target": target})
    return result


def python_reference(fixture: dict[str, Any]) -> tuple[dict[str, str], list[tuple[str, str]], str, str]:
    from onlyalpha.domain.calendar import OnlyTradingCalendar
    from onlyalpha.domain.enums import OnlyOrderSide
    from onlyalpha.domain.identifiers import (
        OnlyAccountId,
        OnlyClusterId,
        OnlyInstrumentId,
        OnlyOrderId,
        OnlyPositionId,
        OnlyRuntimeId,
        OnlyTradeId,
    )
    from onlyalpha.domain.time import OnlyTradingDay
    from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
    from onlyalpha.market.models import OnlySettlementModel, OnlySettlementRule, OnlySettlementTiming
    from onlyalpha.position.identifiers import OnlyPositionAllocationId
    from onlyalpha.settlement.authority import OnlySettlementAuthority
    from onlyalpha.settlement.identifiers import OnlySettlementInstructionId
    from onlyalpha.settlement.identity import only_instruction_identity_payload, only_settlement_instruction_id
    from onlyalpha.settlement.models import (
        OnlyAssetSettlementLeg,
        OnlyCashSettlementLeg,
        OnlySettlementInstruction,
        OnlySettlementLegDirection,
        OnlySettlementScheduleRequest,
        only_settlement_instruction_content_fingerprint,
    )

    p = fixture["policy"]
    assert p["asset_booked"] == p["cash_booked"] == p["cash_trade_available"] == 0
    calendar = OnlyTradingCalendar.from_dict(fixture["calendar"])
    assert calendar.to_dict() == fixture["calendar"]

    def rule(lag: int) -> OnlySettlementRule:
        return (
            OnlySettlementRule(OnlySettlementTiming.T_PLUS_N, lag)
            if lag
            else OnlySettlementRule(OnlySettlementTiming.T_PLUS_ZERO)
        )

    def advance(day: OnlyTradingDay, lag: int) -> OnlyTradingDay:
        candidate = day.value
        for _ in range(lag):
            candidate += timedelta(days=1)
            while not calendar.is_trading_day(candidate):
                candidate += timedelta(days=1)
            assert calendar.is_effective_on(candidate)
        return OnlyTradingDay(candidate)

    model = OnlySettlementModel(
        p["id"],
        rule(p["legal_settled"]),
        rule(p["cash_withdrawable"]),
        rule(p["asset_trade_available"]),
        rule(p["cash_trade_available"]),
    )
    side = OnlyOrderSide(fixture["side"])
    day = OnlyTradingDay(date.fromisoformat(fixture["trading_day"]))
    schedule = model.schedule(OnlySettlementScheduleRequest(side, day), advance)
    schedule_values = dict(
        zip(
            AXES,
            (
                getattr(schedule, key).value.isoformat()
                for key in (
                    "asset_booked_on",
                    "asset_trade_available_on",
                    "cash_booked_on",
                    "cash_trade_available_on",
                    "cash_withdrawable_on",
                    "legal_settlement_on",
                )
            ),
            strict=True,
        )
    )
    scope = fixture["scope"]
    currency = OnlyCurrency.from_dict(fixture["currency"])
    quantity = OnlyQuantity(Decimal(fixture["quantity"]), 0)
    gross = OnlyMoney(Decimal(fixture["gross_notional"]), currency)
    net = (
        gross.amount - Decimal(fixture["charges"]) + Decimal(fixture["rebates"])
        if side is OnlyOrderSide.SELL
        else -gross.amount - Decimal(fixture["charges"]) + Decimal(fixture["rebates"])
    )
    cash_credit = side is OnlyOrderSide.SELL
    instruction = OnlySettlementInstruction(
        OnlySettlementInstructionId("provisional"),
        OnlyRuntimeId(scope["runtime"]),
        OnlyAccountId(scope["account"]),
        OnlyClusterId(scope["cluster"]),
        OnlyInstrumentId.parse(scope["instrument"]),
        OnlyOrderId(fixture["order"]),
        OnlyTradeId(fixture["trade"]),
        OnlyPositionId(fixture["position"]),
        fixture["position_cycle"],
        OnlyPositionAllocationId(fixture["allocation"]),
        fixture["allocation_cycle"],
        side,
        quantity,
        gross,
        OnlyMoney(net, currency),
        day,
        schedule,
        OnlyAssetSettlementLeg(
            OnlySettlementLegDirection.CREDIT if side is OnlyOrderSide.BUY else OnlySettlementLegDirection.DEBIT,
            quantity,
            schedule.asset_booked_on,
            schedule.asset_trade_available_on,
            schedule.legal_settlement_on,
        ),
        OnlyCashSettlementLeg(
            OnlySettlementLegDirection.CREDIT if cash_credit else OnlySettlementLegDirection.DEBIT,
            gross,
            OnlyMoney(abs(net), currency),
            schedule.cash_booked_on,
            schedule.cash_trade_available_on,
            schedule.cash_withdrawable_on,
            schedule.legal_settlement_on,
        ),
        "CONTROLLED_CASH",
        "1",
        "c" * 64,
        "d" * 64,
        "0" * 64,
    )
    instruction = replace(instruction, content_fingerprint=only_settlement_instruction_content_fingerprint(instruction))
    instruction = replace(
        instruction, instruction_id=only_settlement_instruction_id(only_instruction_identity_payload(instruction))
    )
    owner = OnlySettlementAuthority()
    owner.register(instruction)
    owner.register(instruction)
    due = [
        (item.effective_on.value.isoformat(), item.transition.value.lower())
        for item in owner.due_transitions(OnlyTradingDay(date(2026, 12, 31)))
    ]
    return (
        schedule_values,
        due,
        str(owner.require(instruction.instruction_id).status),
        f"{instruction.net_cash_flow.amount:.2f}",
    )


def compare_native(root: Path, executable: Path) -> None:
    def invoke(payload: dict[str, Any]) -> dict[str, Any]:
        completed = subprocess.run(
            [str(executable)], input=json.dumps(payload), text=True, capture_output=True, check=True
        )
        result: dict[str, Any] = json.loads(completed.stdout)
        return result

    for case in cases(root):
        fixture = case["fixture"]
        expected, python_due, status, cash_flow = python_reference(fixture)
        assert expected == case["expected"]
        initial = invoke({"fixture": fixture, "advances": []})
        assert initial["instruction"]["schedule"] == expected
        assert initial["initial"]["status"] == status
        assert initial["instruction"]["cash_flow"] == cash_flow
        assert [(item["effective_on"], item["transition"]) for item in initial["due"]] == python_due
        steps = [] if case["label"] == "T0" else [{"day": case["target"], "time": 2, "version": 1}]
        full = invoke({"fixture": fixture, "advances": steps})
        if steps:
            effect = full["effects"][0]
            assert effect["asset_quantity"] == ("4" if fixture["side"] == "BUY" else "0")
            assert effect["cash_amount"] == ("47.00" if fixture["side"] == "SELL" else "0.00")
        resumed = invoke({"fixture": fixture, "checkpoint": initial["checkpoint"], "advances": steps})
        assert resumed["checkpoint"] == full["checkpoint"]
        closed = invoke({"fixture": fixture, "checkpoint": full["checkpoint"], "advances": []})
        assert closed["due"] == []
        assert next(iter(closed["checkpoint"]["instructions"].values()))["status"] == "COMPLETED"
    print("SETTLEMENT_PYTHON_NATIVE_REFERENCE: PASS")
