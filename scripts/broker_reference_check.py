"""Real deterministic Python Virtual Broker observations compared with native Broker codecs.

This is a technical library comparison, not shipping Web or deployed Runtime acceptance.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onlyalpha.broker.identifiers import OnlyBrokerRequestId  # noqa: E402
from onlyalpha.broker.models import OnlyBrokerCancelRequest  # noqa: E402
from onlyalpha.broker.updates import (  # noqa: E402
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderExpiredUpdate,
    OnlyBrokerOrderRejectedUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.domain.execution import OnlyOrderRejection  # noqa: E402
from onlyalpha.domain.time import OnlyTimestamp  # noqa: E402
from onlyalpha.execution.accepted_identity import only_capture_execution_order_accepted_authority  # noqa: E402
from onlyalpha.execution.fill_identity import (  # noqa: E402
    only_execution_fill_identity_from_update,
    only_execution_fill_payload_fingerprint,
)
from onlyalpha.execution.terminal_identity import only_capture_execution_terminal_authority  # noqa: E402


def domain_fixture() -> dict[str, Any]:
    from scripts.order_reference_check import domain_fixture as order_fixture

    request = cast(dict[str, Any], order_fixture()["request"])
    request["account_id"] = {"schema_version": 1, "value": "account"}
    return {"request": request}


def check_fixture() -> None:
    actual = json.loads((ROOT / "test-data/broker/domain-inputs.json").read_text())
    if actual != domain_fixture():
        raise ValueError("BROKER_DOMAIN_FIXTURE_DRIFT")
    if json.loads((ROOT / "test-data/broker/virtual-v2.json").read_text()) != virtual_corpus():
        raise ValueError("BROKER_VIRTUAL_FIXTURE_DRIFT")


def virtual_corpus() -> list[dict[str, Any]]:
    support = import_module("tests.support.virtual_broker")
    fill_plan = import_module("onlyalpha_plugin_broker_virtual.fill_plan")
    steps = tuple(fill_plan.OnlyVirtualFillScheduleStepSpec(i, quantity=Decimal(q)) for i, q in ((1, "40"), (2, "60")))
    clock, gateway, updates = support.schedule_gateway(steps=steps)
    support.accept_scheduled_order(clock, gateway)
    current = support.bar(date(2026, 1, 5), 1)
    clock.advance_to(current.ts_event)
    gateway.on_bar(current)
    request = support.order(1)
    gateway.cancel_order(
        OnlyBrokerCancelRequest(
            OnlyBrokerRequestId("cancel"),
            support.ACCOUNT,
            request.order_id,
            None,
            OnlyTimestamp.from_datetime(current.ts_event),
        )
    )
    gateway.run_due()
    future = support.bar(date(2026, 1, 5), 2)
    clock.advance_to(future.ts_event)
    gateway.on_bar(future)
    trades = [u for u in updates if isinstance(u, OnlyBrokerTradeUpdate)]
    terminals = [u for u in updates if isinstance(u, OnlyBrokerOrderCancelledUpdate)]
    accepted = [u for u in updates if isinstance(u, OnlyBrokerOrderAcceptedUpdate)]
    if (
        len(trades) != 1
        or trades[0].fill.quantity.value != Decimal("40")
        or trades[0].fill.price.value != Decimal("10")
        or len(terminals) != 1
        or len(accepted) != 1
    ):
        raise ValueError("VIRTUAL_BROKER_PARTIAL_FILL_CANCEL_CONTRACT")
    samples: list[Any] = [accepted[0], trades[0], terminals[0]]
    # Reconnect/REST provenance must not alter any canonical execution identity or payload.
    samples.extend(
        replace(
            u,
            update_id=type(u.update_id)(f"rest-{i}"),
            source_sequence=100 + i,
            ts_init=OnlyTimestamp(u.ts_init.unix_nanos + 1),
        )
        for i, u in enumerate(samples[:])
    )
    terminal = terminals[0]
    samples.append(
        OnlyBrokerOrderExpiredUpdate(
            runtime_id=terminal.runtime_id,
            gateway_id=terminal.gateway_id,
            account_id=terminal.account_id,
            update_id=type(terminal.update_id)("expired"),
            source_sequence=200,
            ts_event=terminal.ts_event,
            ts_init=terminal.ts_init,
            correlation_id=terminal.correlation_id,
            causation_id=terminal.causation_id,
            order_id=terminal.order_id,
            venue_order_id=None,
        )
    )
    samples.append(replace(trades[0], fill=replace(trades[0].fill, venue_trade_id=None, reference_price=None)))
    common = {
        name: getattr(terminal, name)
        for name in (
            "runtime_id",
            "gateway_id",
            "account_id",
            "source_sequence",
            "ts_event",
            "ts_init",
            "correlation_id",
            "causation_id",
            "order_id",
        )
    }
    samples.append(
        OnlyBrokerOrderRejectedUpdate(
            **common,
            update_id=type(terminal.update_id)("rejected"),
            venue_order_id=None,
            rejection=OnlyOrderRejection("拒绝", "额度不足"),
        )
    )
    result = []
    for index, update in enumerate(samples):
        scope = {
            "engine": "engine",
            "runtime": str(update.runtime_id),
            "gateway": str(update.gateway_id),
            "account": str(update.account_id),
            "generation": "a" * 64,
            "runtime_kind": "BACKTEST",
        }
        payload: dict[str, Any]
        if isinstance(update, OnlyBrokerOrderAcceptedUpdate):
            kind, payload = "ACCEPTED", {"order": str(update.order_id), "venue": str(update.venue_order_id)}
            authority = only_capture_execution_order_accepted_authority(update)
            identity, fingerprint = authority.accepted_identity, authority.payload_fingerprint
        elif isinstance(update, OnlyBrokerTradeUpdate):
            kind, payload = "TRADE", {"order": str(update.order_id), "fill": update.fill.to_dict()}
            identity, fingerprint = (
                only_execution_fill_identity_from_update(update),
                only_execution_fill_payload_fingerprint(update),
            )
        else:
            kind = (
                "CANCELLED"
                if isinstance(update, OnlyBrokerOrderCancelledUpdate)
                else "REJECTED"
                if isinstance(update, OnlyBrokerOrderRejectedUpdate)
                else "EXPIRED"
            )
            payload = {
                "order": str(update.order_id),
                "venue": None if update.venue_order_id is None else str(update.venue_order_id),
                "reason": f"{update.rejection.code}:{update.rejection.message}"
                if isinstance(update, OnlyBrokerOrderRejectedUpdate)
                else "",
            }
            authority_terminal = only_capture_execution_terminal_authority(update)
            identity, fingerprint = authority_terminal.terminal_identity, authority_terminal.payload_fingerprint
        fact = {
            "scope": scope,
            "session": "stream" if index < 3 else "rest",
            "update_id": str(update.update_id),
            "source_sequence": update.source_sequence,
            "ts_event": update.ts_event.unix_nanos,
            "ts_init": update.ts_init.unix_nanos,
            "correlation": update.correlation_id,
            "causation": update.causation_id,
            "quality": list(update.quality_flags),
            "kind": kind,
            "payload": payload,
        }
        result.append({"fact": fact, "identity": identity, "fingerprint": fingerprint})
    return result


if __name__ == "__main__":
    check_fixture()
    print(json.dumps(virtual_corpus(), ensure_ascii=False, sort_keys=True))
