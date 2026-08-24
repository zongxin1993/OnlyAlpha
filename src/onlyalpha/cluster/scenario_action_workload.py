"""Deterministic Scenario command workload, explicitly outside Strategy semantics."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import cast

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyOrderId, OnlyOrderRequestId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.runtime.context import OnlyClusterContext


class OnlyScenarioActionWorkload:
    """Executes predeclared acceptance actions; it is not a Strategy or signal author."""

    def __init__(self, actions: tuple[Mapping[str, object], ...]) -> None:
        self._actions = actions
        metadata = next((item.get("result_metadata") for item in actions if "result_metadata" in item), {})
        if not isinstance(metadata, Mapping):
            raise ValueError("Scenario result metadata must be an object")
        self._result_metadata = dict(metadata)
        self._context: OnlyClusterContext | None = None
        self._bar_sequence = 0
        self._orders: dict[str, OnlyOrderId] = {}
        self._records: list[dict[str, object]] = []

    def bind(self, context: OnlyClusterContext) -> None:
        if self._context is not None:
            raise RuntimeError("Scenario Action Workload can be bound only once")
        self._context = context

    def on_bar(self, bar: OnlyBar) -> None:
        del bar
        if self._context is None:
            raise RuntimeError("Scenario Action Workload is not bound")
        self._bar_sequence += 1
        orders = self._context.orders
        instruments = self._context.instruments
        for action in self._actions:
            if int(str(action["sequence"])) != self._bar_sequence:
                continue
            action_id = str(action["action_id"])
            if action["type"] == "CANCEL_ORDER":
                cancel_result = orders.cancel(self._orders[str(action["target_action_id"])])
                self._records.append(
                    {
                        "record_type": "CANCEL",
                        "action_id": action_id,
                        "status": "EXECUTED",
                        "order_id": str(cancel_result.snapshot.order_id),
                        "requested": cancel_result.requested,
                        "cancelled": cancel_result.cancelled,
                        "order_status": cancel_result.snapshot.status.value,
                        "error": cancel_result.error,
                    }
                )
                continue
            instrument_id = OnlyInstrumentId.parse(str(action["instrument_id"]))
            instrument = cast(OnlyInstrument, instruments.require(instrument_id))
            price_raw = action.get("price")
            raw_tags = action.get("tags", ())
            if not isinstance(raw_tags, (list, tuple)) or any(not isinstance(item, str) for item in raw_tags):
                raise ValueError("Scenario action tags must be an array of strings")
            request = OnlyOrderRequest(
                OnlyOrderRequestId(f"scenario-{self._context.cluster_id}:{action_id}"),
                instrument_id,
                OnlyOrderSide(str(action["side"])),
                OnlyOrderType(str(action["order_type"])),
                OnlyQuantity(Decimal(str(action["quantity"])), instrument.quantity_precision),
                OnlyTimeInForce(str(action.get("time_in_force", "DAY"))),
                offset=OnlyOffset(str(action.get("offset", "NONE"))),
                price=None if price_raw is None else OnlyPrice(Decimal(str(price_raw)), instrument.price_precision),
                tags=tuple(raw_tags),
                metadata={"scenario_action_id": action_id},
            )
            submit_result = orders.submit(request)
            if submit_result.order_id is not None:
                self._orders[action_id] = submit_result.order_id
            rejection = submit_result.risk_rejection
            details = {} if rejection is None else rejection.details
            self._records.append(
                {
                    "record_type": "SUBMISSION",
                    "action_id": action_id,
                    "tag": str(action.get("tag", action_id)),
                    "side": str(action["side"]),
                    "status": "EXECUTED" if submit_result.created else "REJECTED",
                    "request_id": str(request.request_id),
                    "created": submit_result.created,
                    "submitted": submit_result.submitted,
                    "order_id": None if submit_result.order_id is None else str(submit_result.order_id),
                    "error": submit_result.error,
                    "risk_rejection_code": None if rejection is None else rejection.code.value,
                    "risk_rejection": "" if rejection is None else rejection.message,
                    "market_reason_code": details.get("market_reason_code"),
                    "market_rule_code": details.get("market_rule_code"),
                    "market_product_id": details.get("market_product_id"),
                    "market_product_version": details.get("market_product_version"),
                    "market_reference_fingerprint": details.get("market_reference_fingerprint"),
                    "market_compiled_rule_fingerprint": details.get("market_compiled_rule_fingerprint"),
                }
            )

    def build_result_extension(self) -> Mapping[str, object]:
        submissions = [dict(item) for item in self._records if item.get("record_type") == "SUBMISSION"]
        cancellations = [
            {
                "order_id": item["order_id"],
                "requested": item["requested"],
                "cancelled": item["cancelled"],
                "status": item["order_status"],
                "error": item["error"],
            }
            for item in self._records
            if item.get("record_type") == "CANCEL"
        ]
        return {
            **self._result_metadata,
            "bar_count": self._bar_sequence,
            "submission_results": submissions,
            "cancel_results": cancellations,
            "scenario_actions": tuple(self._records),
        }

    def capture_checkpoint(self) -> object:
        return {
            "schema_version": 1,
            "bar_sequence": self._bar_sequence,
            "orders": {key: str(value) for key, value in sorted(self._orders.items())},
            "records": list(self._records),
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema_version",
            "bar_sequence",
            "orders",
            "records",
        }:
            raise ValueError("Scenario Action checkpoint fields are invalid")
        if payload["schema_version"] != 1 or not isinstance(payload["bar_sequence"], int):
            raise ValueError("Scenario Action checkpoint schema is invalid")
        orders = payload["orders"]
        records = payload["records"]
        if not isinstance(orders, Mapping) or not isinstance(records, list):
            raise ValueError("Scenario Action checkpoint payload is invalid")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in orders.items()):
            raise ValueError("Scenario Action checkpoint orders are invalid")
        if any(not isinstance(item, dict) for item in records):
            raise ValueError("Scenario Action checkpoint records are invalid")
        self._bar_sequence = payload["bar_sequence"]
        self._orders = {str(key): OnlyOrderId(str(value)) for key, value in orders.items()}
        self._records = [dict(item) for item in records]


__all__ = ["OnlyScenarioActionWorkload"]
