"""Actual Python execution processor comparison on an independently expected common subset.

Technical hermetic proof only; identities/artifacts and projection codecs are not equated.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onlyalpha.execution.committed import OnlyCommittedExecutionFact  # noqa: E402

# Hermetic test fixtures are loaded at the comparison boundary; they are outside the
# production strict-type lane and exercise the actual processor at runtime.
_harness = import_module("tests.execution.support.generic_t0_trade_harness")


# Generic T0 fee pack rate is 0.001: 100*12*0.001=1.20, 300*12*0.001=3.60.
EXPECTED = [
    {
        "quantity_after": "300",
        "cost_after": "3000",
        "cash_delta": "1198.80",
        "realized_delta": "200.00",
        "fees": "1.20",
    },
    {"quantity_after": "0", "cost_after": "0", "cash_delta": "3596.40", "realized_delta": "600.00", "fees": "3.60"},
]


def domain_fixture() -> dict[str, object]:
    import copy
    from typing import Any, cast

    from onlyalpha.domain.execution import OnlyOrderRequest
    from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId
    from onlyalpha.domain.time import OnlyTimestamp
    from scripts.order_reference_check import _manager, _request
    from scripts.order_reference_check import domain_fixture as order_fixture
    from tests.order.fee_contract import only_test_zero_fee_contract

    fixture = order_fixture()
    manager = _manager()
    manager.create_order(_request(), OnlyClusterId("cluster"), OnlyAccountId("account"), OnlyTimestamp(1))
    request = copy.deepcopy(cast(dict[str, Any], fixture["request"]))
    request["request_id"]["value"] = "request-2"
    request["side"] = "SELL"
    request["execution_intent"]["side"] = "SELL"
    request["execution_intent"]["position_effect"] = "CLOSE"
    request["price"]["value"] = "12.00"
    close = manager.create_order(
        OnlyOrderRequest.from_dict(request), OnlyClusterId("cluster"), OnlyAccountId("account"), OnlyTimestamp(5)
    )
    fixture["second_fee_contract"] = dict(
        zip(
            ("binding", "estimate", "funding"),
            (part.to_dict() for part in only_test_zero_fee_contract(close.snapshot, OnlyTimestamp(5))),
            strict=True,
        )
    )
    return fixture


def check_fixture() -> None:
    import json

    expected = json.dumps(domain_fixture(), sort_keys=True, separators=(",", ":")) + "\n"
    if (ROOT / "test-data/execution/domain-inputs.json").read_text() != expected:
        raise ValueError("EXECUTION_DOMAIN_INPUT_FIXTURE_DRIFT")


def reference_outputs() -> list[dict[str, str]]:
    env, context, _ = _harness.only_test_generic_t0_long_close_context(
        open_quantity="400", close_quantity="400", fill_quantity="100", fill_price="12.00"
    )
    rows = []
    for index in range(2):
        update = (
            context.update
            if index == 0
            else _harness.only_test_generic_t0_long_close_update(
                env, context.update.order_id, suffix="rust-common-final", fill_quantity="300", fill_price="12.00"
            )
        )
        result = env.runtime.execution_processor.process(update)
        if result.status.value != "APPLIED":
            raise ValueError("EXECUTION_PYTHON_REFERENCE_NOT_APPLIED")
        records = env.runtime.execution_transaction_query.transactions_for_order(update.runtime_id, update.order_id)
        facts = [item.fact for item in records if isinstance(item.fact, OnlyCommittedExecutionFact)]
        fact = facts[-1]
        rows.append(
            {
                "quantity_after": str(fact.position_quantity_after.normalize()),
                "cost_after": format(fact.position_cumulative_open_price_quantity_after.normalize(), "f"),
                "cash_delta": format(fact.account_cash_delta.amount, ".2f"),
                "realized_delta": format(fact.realized_pnl_delta.amount, ".2f"),
                "fees": format(fact.incremental_fee_charges.amount - fact.incremental_fee_rebates.amount, ".2f"),
            }
        )
    # Decimal equality must not disguise changed identity/provenance; only numeric display spelling is normalized here.
    for row in rows:
        row["quantity_after"] = format(Decimal(row["quantity_after"]), "f")
    if rows != EXPECTED:
        raise ValueError(f"EXECUTION_PYTHON_LITERAL_CONFLICT:{rows}")
    return rows


def compare_native_outputs(native: list[dict[str, str]]) -> None:
    if native != EXPECTED or native != reference_outputs():
        raise ValueError("EXECUTION_PYTHON_RUST_CONFLICT")


if __name__ == "__main__":
    import json

    if sys.argv[1:] == ["--write-fixture"]:
        (ROOT / "test-data/execution/domain-inputs.json").write_text(
            json.dumps(domain_fixture(), sort_keys=True, separators=(",", ":")) + "\n"
        )
    elif sys.argv[1:]:
        raise SystemExit("only --write-fixture is supported")
    else:
        check_fixture()
        print(reference_outputs())
