"""Actual Python common collateral reference and independent native recovery proof.

Component identities, quantity allocation and strict history are not asserted Python parity.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fee_contracts() -> dict[str, Any]:
    from onlyalpha.domain.execution import OnlyOrderRequest
    from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId
    from onlyalpha.domain.time import OnlyTimestamp
    from scripts.order_reference_check import _manager, _request
    from tests.order.fee_contract import only_test_zero_fee_contract

    manager = _manager()
    result = {}
    for ordinal, at in ((1, 1), (2, 4), (3, 7)):
        request: dict[str, Any] = _request(f"request-{ordinal}").to_dict()
        if ordinal == 3:
            request["side"] = request["execution_intent"]["side"] = "SELL"
            request["execution_intent"]["position_effect"] = "CLOSE"
            request["price"]["value"] = "12.00"
        order = manager.create_order(
            OnlyOrderRequest.from_dict(request), OnlyClusterId("cluster"), OnlyAccountId("account"), OnlyTimestamp(at)
        )
        if ordinal > 1:
            result[str(ordinal)] = dict(
                zip(
                    ("binding", "estimate", "funding"),
                    (part.to_dict() for part in only_test_zero_fee_contract(order.snapshot, OnlyTimestamp(at))),
                    strict=True,
                )
            )
    return result


def check_fixture(root: Path = ROOT) -> None:
    fixture = json.loads((root / "test-data/margin/common-v1.json").read_text())
    if fixture["fee_contracts"] != fee_contracts():
        raise ValueError("MARGIN_FEE_CONTRACT_FIXTURE_DRIFT")


def cases(root: Path = ROOT) -> list[dict[str, Any]]:
    fixture = json.loads((root / "test-data/margin/common-v1.json").read_text())
    result = []
    for mode, isolation, side in (
        ("CROSS", None, "LONG"),
        ("CROSS", None, "SHORT"),
        ("ISOLATED", "instrument-long", "LONG"),
        ("ISOLATED", "instrument-short", "SHORT"),
    ):
        template = copy.deepcopy(fixture["reserve"])
        template.update(mode=mode, isolation=isolation, position_side=side)
        steps = [
            dict(action="RESERVE", quantity="4", amount="100.00", maintenance="0.00"),
            dict(action="OCCUPY", quantity="2", amount="60.00", maintenance="48.00"),
            dict(action="RELEASE_RESERVED", quantity="2", amount="40.00", maintenance="0.00"),
            dict(action="RELEASE_OCCUPIED", quantity="1", amount="30.00", maintenance="24.00"),
            dict(action="RELEASE_OCCUPIED", quantity="1", amount="30.00", maintenance="24.00"),
        ]
        result.append(dict(config=fixture["config"], template=template, steps=steps))
    return result


EXPECTED = [
    ["100.00", "0.00", "0.00", "0.00"],
    ["40.00", "60.00", "0.00", "48.00"],
    ["0.00", "60.00", "40.00", "48.00"],
    ["0.00", "30.00", "70.00", "24.00"],
    ["0.00", "0.00", "100.00", "0.00"],
]
FIELDS = ("reserved", "occupied", "released", "maintenance")


def python_reference(case: dict[str, Any]) -> list[list[str]]:
    from onlyalpha.domain.identifiers import OnlyRuntimeId
    from onlyalpha.domain.time import OnlyTimestamp
    from onlyalpha.margin.manager import OnlyMarginManager
    from onlyalpha.market.runtime_rules import OnlyMarginInstruction

    manager = OnlyMarginManager(OnlyRuntimeId(case["config"]["runtime"]))
    rows = []
    template = case["template"]
    for index, step in enumerate(case["steps"], 1):
        release = step["action"].startswith("RELEASE")
        trade = "" if step["action"] in ("RESERVE", "RELEASE_RESERVED") else f"trade-{index}"
        order = "closing-order" if step["action"] == "RELEASE_OCCUPIED" else template["source_order"]
        instruction = OnlyMarginInstruction(
            "RELEASE" if release else step["action"],
            template["scope"]["account"],
            template["scope"]["instrument"],
            case["config"]["currency"]["code"],
            Decimal(step["amount"]),
            Decimal(step["maintenance"]),
            order,
            trade,
            OnlyTimestamp(index),
            template["mode"],
            template["isolation"],
            template["position_side"],
        )
        manager.apply(instruction)
        state = manager.get(template["source_order"])
        assert state is not None
        rows.append(
            [
                format(value, ".2f")
                for value in (state.reserved, state.occupied, state.released, state.maintenance_required)
            ]
        )
    return rows


def compare_native(root: Path, executable: Path) -> None:
    check_fixture(root)

    def invoke(frame: dict[str, Any]) -> dict[str, Any]:
        response = subprocess.run(
            [str(executable)], input=json.dumps(frame), text=True, capture_output=True, check=True
        )
        value: dict[str, Any] = json.loads(response.stdout)
        return value

    for case in cases(root):
        assert python_reference(case) == EXPECTED
        result = invoke(case)
        assert [[s[k] for k in FIELDS] for s in result["snapshots"]] == EXPECTED
        assert result["snapshots"][-1]["status"] == "CLOSED"
        initial = invoke(dict(case, steps=case["steps"][:2]))
        resumed = invoke(dict(case, checkpoint=initial["checkpoint"], steps=case["steps"][2:]))
        assert resumed["checkpoint"] == result["checkpoint"]
        assert resumed["snapshots"] == result["snapshots"][2:]
    print(
        f"MARGIN_PYTHON_NATIVE_REFERENCE: PASS artifact_sha256={hashlib.sha256(executable.read_bytes()).hexdigest()}",
        flush=True,
    )
