"""Strict YAML/JSON Scenario parser; it never evaluates market rules."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import NoReturn, TypeVar, cast

import yaml  # type: ignore[import-untyped]

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType, OnlyRuntimeMode, OnlyTimeInForce
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.scenario.errors import OnlyScenarioError, OnlyScenarioErrorCode
from onlyalpha.scenario.models import (
    OnlyMarketScenario,
    OnlyMarketScenarioId,
    OnlyMarketScenarioVersion,
    OnlyScenarioAction,
    OnlyScenarioAssertionOperator,
    OnlyScenarioBar,
    OnlyScenarioCancelOrderCommand,
    OnlyScenarioCommandType,
    OnlyScenarioExpectation,
    OnlyScenarioFactType,
    OnlyScenarioRuntimeSpec,
    OnlyScenarioSubmitOrderCommand,
    OnlyScenarioTrigger,
    OnlyScenarioTriggerType,
)

OnlyScenarioEnumT = TypeVar("OnlyScenarioEnumT", bound=Enum)


class OnlyMarketScenarioParser:
    _ROOT = frozenset(
        {
            "schema_version",
            "scenario",
            "runtime",
            "market",
            "reference",
            "data",
            "actions",
            "expectations",
            "extensions",
        }
    )

    def load(self, path: str | Path) -> OnlyMarketScenario:
        source = Path(path).expanduser().resolve()
        try:
            text = source.read_text(encoding="utf-8")
            raw = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
        except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
            raise OnlyScenarioError(OnlyScenarioErrorCode.SCENARIO_SCHEMA_UNSUPPORTED, str(exc)) from exc
        return self.parse(raw, source_path=source)

    def parse(self, value: object, *, source_path: str | Path = "<scenario>") -> OnlyMarketScenario:
        root = self._mapping(value, "$")
        self._unknown(root, self._ROOT, "$")
        schema_version = self._string(root.get("schema_version"), "$.schema_version")
        if schema_version != "1":
            self._fail(OnlyScenarioErrorCode.SCENARIO_SCHEMA_UNSUPPORTED, "$.schema_version", schema_version)
        metadata = self._mapping(root.get("scenario"), "$.scenario")
        self._unknown(metadata, {"id", "version", "description"}, "$.scenario")
        runtime_raw = self._mapping(root.get("runtime"), "$.runtime")
        self._unknown(runtime_raw, {"mode", "start_time", "end_time", "base_currency"}, "$.runtime")
        runtime = OnlyScenarioRuntimeSpec(
            self._enum(OnlyRuntimeMode, runtime_raw.get("mode"), "$.runtime.mode"),
            self._timestamp(runtime_raw.get("start_time"), "$.runtime.start_time"),
            self._timestamp(runtime_raw.get("end_time"), "$.runtime.end_time"),
            self._string(runtime_raw.get("base_currency"), "$.runtime.base_currency"),
        )
        reference_raw = self._mapping(root.get("reference"), "$.reference")
        product = OnlyClusterRunConfig.from_mapping(
            self._product_config(root, runtime_raw, reference_raw), source_path=source_path
        )
        instruments = product.reference_data.instrument_by_id
        bars = self._bars(self._mapping(root.get("data"), "$.data"), instruments)
        actions = self._actions(self._list(root.get("actions"), "$.actions"), instruments)
        expectations = self._expectations(self._list(root.get("expectations", []), "$.expectations"))
        self._validate_references(bars, actions, expectations)
        return OnlyMarketScenario(
            schema_version,
            OnlyMarketScenarioId(self._string(metadata.get("id"), "$.scenario.id")),
            OnlyMarketScenarioVersion(self._string(metadata.get("version"), "$.scenario.version")),
            self._string(metadata.get("description", ""), "$.scenario.description", allow_empty=True),
            runtime,
            product.market,
            product.reference_data,
            bars,
            actions,
            expectations,
            product,
            self._mapping(root.get("extensions", {}), "$.extensions"),
        )

    def _product_config(
        self, root: Mapping[str, object], runtime: Mapping[str, object], reference: Mapping[str, object]
    ) -> dict[str, object]:
        self._unknown(reference, {"calendars", "instruments"}, "$.reference")
        instruments = self._list(reference.get("instruments"), "$.reference.instruments")
        instrument_id = self._string(
            self._mapping(instruments[0], "$.reference.instruments[0]").get("instrument_id"), "instrument_id"
        )
        bars = self._list(self._mapping(root.get("data"), "$.data").get("bars"), "$.data.bars")
        actions = self._list(root.get("actions"), "$.actions")
        strategy_actions = []
        for raw_action in actions:
            action = self._mapping(raw_action, "$.actions[]")
            trigger = self._mapping(action.get("trigger"), "$.actions[].trigger")
            command = self._mapping(action.get("command"), "$.actions[].command")
            item: dict[str, object] = {
                "action_id": action["action_id"],
                "sequence": trigger.get("sequence", 0),
                "type": command["type"],
            }
            if command["type"] == "CANCEL_ORDER":
                item["target_action_id"] = command["action_id"]
            else:
                item.update(
                    {
                        "instrument_id": command["instrument_id"],
                        "side": command["side"],
                        "order_type": command["order_type"],
                        "quantity": command["quantity"],
                        "offset": "NONE"
                        if command.get("position_effect", "AUTO") == "AUTO"
                        else command["position_effect"],
                        "time_in_force": command.get("time_in_force", "DAY"),
                    }
                )
                if command.get("price") is not None:
                    item["price"] = command["price"]
            strategy_actions.append(item)
        exact_bars = []
        for raw_bar in bars:
            bar = self._mapping(raw_bar, "$.data.bars[]")
            event = self._timestamp(bar["ts_event"], "$.data.bars[].ts_event")
            initialized = self._timestamp(bar.get("ts_init", bar["ts_event"]), "$.data.bars[].ts_init")
            exact_bars.append(
                {
                    "instrument_id": bar["instrument_id"],
                    "ts_event_ns": int(event.timestamp() * 1_000_000_000),
                    "ts_init_ns": int(initialized.timestamp() * 1_000_000_000),
                    "sequence": bar["sequence"],
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar["volume"],
                }
            )
        return {
            "schema_version": "1.0",
            "market": dict(self._mapping(root.get("market"), "$.market")),
            "cluster": {
                "cluster_id": "scenario",
                "account_id": "scenario-account",
                "enabled": True,
                "runtime_type": runtime["mode"],
            },
            "runtime": {
                "start_time": runtime["start_time"],
                "end_time": runtime["end_time"],
                "base_currency": runtime["base_currency"],
            },
            "reference_data": dict(reference),
            "universes": [{"universe_id": "scenario-universe", "type": "STATIC", "instruments": [instrument_id]}],
            "data_sources": [
                {
                    "source_id": "scenario-data",
                    "plugin": "scenario-exact",
                    "data_version": "scenario-v1",
                    "coverage": {"instrument_ids": [instrument_id]},
                    "extensions": {"bars": exact_bars},
                }
            ],
            "accounts": [
                {
                    "account_id": "scenario-account",
                    "gateway_id": "scenario-broker",
                    "initial_cash": {"value": "1000000", "currency": runtime["base_currency"]},
                }
            ],
            "brokers": [
                {
                    "gateway_id": "scenario-broker",
                    "plugin": "virtual",
                    "fees": {"mode": "NONE"},
                    "extensions": {},
                }
            ],
            "strategy": {
                "class_path": "onlyalpha.scenario.action_strategy:OnlyScenarioActionStrategy",
                "config_path": "onlyalpha.scenario.action_strategy:OnlyScenarioActionStrategyConfig",
                "extensions": {
                    "strategy_id": "scenario-action-strategy",
                    "factor_id": "scenario-bar-factor",
                    "actions": strategy_actions,
                },
            },
            "factors": [
                {
                    "factor_id": "scenario-bar-factor",
                    "factor_type": "TIME_SERIES",
                    "class_path": "onlyalpha.scenario.action_strategy:OnlyScenarioBarFactor",
                    "config_path": "onlyalpha.scenario.action_strategy:OnlyScenarioBarFactorConfig",
                    "required": True,
                    "subscriptions": {
                        "instrument_bars": [
                            {
                                "instrument_id": instrument_id,
                                "bar_specification": {
                                    "step": 1,
                                    "aggregation": "TIME",
                                    "price_type": "LAST",
                                    "source": "EXTERNAL",
                                },
                                "role": "PRIMARY",
                            }
                        ]
                    },
                    "indicators": [],
                }
            ],
        }

    def _bars(
        self, data: Mapping[str, object], instruments: Mapping[OnlyInstrumentId, OnlyInstrument]
    ) -> tuple[OnlyScenarioBar, ...]:
        self._unknown(data, {"bars"}, "$.data")
        values: list[OnlyScenarioBar] = []
        for index, raw in enumerate(self._list(data.get("bars"), "$.data.bars")):
            path = f"$.data.bars[{index}]"
            item = self._mapping(raw, path)
            self._unknown(
                item,
                {"instrument_id", "ts_event", "ts_init", "sequence", "open", "high", "low", "close", "volume"},
                path,
            )
            instrument_id = OnlyInstrumentId.parse(self._string(item.get("instrument_id"), f"{path}.instrument_id"))
            if instrument_id not in instruments:
                self._fail(
                    OnlyScenarioErrorCode.SCENARIO_REFERENCE_MISSING, f"{path}.instrument_id", str(instrument_id)
                )
            values.append(
                OnlyScenarioBar(
                    instrument_id,
                    self._timestamp(item.get("ts_event"), f"{path}.ts_event"),
                    self._timestamp(item.get("ts_init", item.get("ts_event")), f"{path}.ts_init"),
                    self._integer(item.get("sequence"), f"{path}.sequence"),
                    *(
                        self._decimal(item.get(name), f"{path}.{name}")
                        for name in ("open", "high", "low", "close", "volume")
                    ),
                )
            )
        ordered = tuple(sorted(values, key=lambda item: (item.ts_event, str(item.instrument_id), item.sequence)))
        if len({item.sequence for item in ordered}) != len(ordered) or any(
            a.ts_event > b.ts_event for a, b in zip(ordered, ordered[1:], strict=False)
        ):
            self._fail(
                OnlyScenarioErrorCode.SCENARIO_TRIGGER_INVALID, "$.data.bars", "non-unique/non-monotonic sequence"
            )
        return ordered

    def _actions(
        self, values: list[object], instruments: Mapping[OnlyInstrumentId, OnlyInstrument]
    ) -> tuple[OnlyScenarioAction, ...]:
        actions: list[OnlyScenarioAction] = []
        for index, raw in enumerate(values):
            path = f"$.actions[{index}]"
            item = self._mapping(raw, path)
            self._unknown(item, {"action_id", "trigger", "command"}, path)
            action_id = self._string(item.get("action_id"), f"{path}.action_id")
            trigger_raw = self._mapping(item.get("trigger"), f"{path}.trigger")
            trigger_type = self._enum(OnlyScenarioTriggerType, trigger_raw.get("type"), f"{path}.trigger.type")
            trigger = OnlyScenarioTrigger(
                trigger_type,
                self._optional_integer(trigger_raw.get("sequence"), f"{path}.trigger.sequence"),
                self._optional_timestamp(trigger_raw.get("timestamp"), f"{path}.trigger.timestamp"),
                None if trigger_raw.get("reference") is None else str(trigger_raw["reference"]),
            )
            command_raw = self._mapping(item.get("command"), f"{path}.command")
            command_type = self._enum(OnlyScenarioCommandType, command_raw.get("type"), f"{path}.command.type")
            command: OnlyScenarioCancelOrderCommand | OnlyScenarioSubmitOrderCommand
            if command_type is OnlyScenarioCommandType.CANCEL_ORDER:
                command = OnlyScenarioCancelOrderCommand(
                    self._string(command_raw.get("action_id"), f"{path}.command.action_id")
                )
            else:
                instrument_id = OnlyInstrumentId.parse(
                    self._string(command_raw.get("instrument_id"), f"{path}.command.instrument_id")
                )
                instrument = instruments.get(instrument_id)
                if instrument is None:
                    self._fail(
                        OnlyScenarioErrorCode.SCENARIO_REFERENCE_MISSING,
                        f"{path}.command.instrument_id",
                        str(instrument_id),
                    )
                quantity_precision = instrument.quantity_precision
                price_precision = instrument.price_precision
                price_value = command_raw.get("price")
                offset_value = str(command_raw.get("position_effect", "AUTO"))
                offset = OnlyOffset.NONE if offset_value == "AUTO" else OnlyOffset(offset_value)
                command = OnlyScenarioSubmitOrderCommand(
                    instrument_id,
                    self._enum(OnlyOrderSide, command_raw.get("side"), f"{path}.command.side"),
                    self._enum(OnlyOrderType, command_raw.get("order_type"), f"{path}.command.order_type"),
                    OnlyQuantity(
                        self._decimal(command_raw.get("quantity"), f"{path}.command.quantity"), quantity_precision
                    ),
                    offset,
                    self._enum(
                        OnlyTimeInForce, command_raw.get("time_in_force", "DAY"), f"{path}.command.time_in_force"
                    ),
                    None
                    if price_value is None
                    else OnlyPrice(self._decimal(price_value, f"{path}.command.price"), price_precision),
                )
            actions.append(OnlyScenarioAction(action_id, trigger, command))
        if len({item.action_id for item in actions}) != len(actions):
            self._fail(OnlyScenarioErrorCode.SCENARIO_ACTION_DUPLICATE, "$.actions", "duplicate action_id")
        return tuple(actions)

    def _expectations(self, values: list[object]) -> tuple[OnlyScenarioExpectation, ...]:
        result: list[OnlyScenarioExpectation] = []
        for index, raw in enumerate(values):
            path = f"$.expectations[{index}]"
            item = self._mapping(raw, path)
            self._unknown(
                item, {"assertion_id", "fact", "selector", "field", "operator", "expected", "tolerance"}, path
            )
            tolerance = item.get("tolerance")
            result.append(
                OnlyScenarioExpectation(
                    self._string(item.get("assertion_id"), f"{path}.assertion_id"),
                    self._enum(OnlyScenarioFactType, item.get("fact"), f"{path}.fact"),
                    self._mapping(item.get("selector", {}), f"{path}.selector"),
                    None if item.get("field") is None else str(item["field"]),
                    self._enum(OnlyScenarioAssertionOperator, item.get("operator"), f"{path}.operator"),
                    item.get("expected"),
                    None if tolerance is None else self._decimal(tolerance, f"{path}.tolerance"),
                )
            )
        if len({item.assertion_id for item in result}) != len(result):
            self._fail(OnlyScenarioErrorCode.SCENARIO_EXPECTATION_INVALID, "$.expectations", "duplicate assertion_id")
        return tuple(result)

    def _validate_references(
        self,
        bars: tuple[OnlyScenarioBar, ...],
        actions: tuple[OnlyScenarioAction, ...],
        expectations: tuple[OnlyScenarioExpectation, ...],
    ) -> None:
        del bars, expectations
        action_ids = {item.action_id for item in actions}
        for action in actions:
            reference = action.trigger.reference
            if action.trigger.trigger_type is OnlyScenarioTriggerType.AFTER_ACTION and reference not in action_ids:
                self._fail(
                    OnlyScenarioErrorCode.SCENARIO_REFERENCE_MISSING,
                    f"$.actions.{action.action_id}.trigger.reference",
                    str(reference),
                )
            if (
                isinstance(action.command, OnlyScenarioCancelOrderCommand)
                and action.command.action_id not in action_ids
            ):
                self._fail(
                    OnlyScenarioErrorCode.SCENARIO_REFERENCE_MISSING,
                    f"$.actions.{action.action_id}.command.action_id",
                    action.command.action_id,
                )

    @staticmethod
    def _unknown(value: Mapping[str, object], allowed: set[str] | frozenset[str], path: str) -> None:
        unknown = sorted(set(value) - set(allowed))
        if unknown:
            raise OnlyScenarioError(OnlyScenarioErrorCode.SCENARIO_FIELD_UNKNOWN, ", ".join(unknown), path=path)

    @staticmethod
    def _mapping(value: object, path: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
            raise OnlyScenarioError(OnlyScenarioErrorCode.SCENARIO_SCHEMA_UNSUPPORTED, "must be an object", path=path)
        return cast(Mapping[str, object], value)

    @staticmethod
    def _list(value: object, path: str) -> list[object]:
        if not isinstance(value, list):
            raise OnlyScenarioError(OnlyScenarioErrorCode.SCENARIO_SCHEMA_UNSUPPORTED, "must be an array", path=path)
        return value

    @staticmethod
    def _string(value: object, path: str, *, allow_empty: bool = False) -> str:
        if not isinstance(value, str) or (not allow_empty and not value):
            raise OnlyScenarioError(OnlyScenarioErrorCode.SCENARIO_SCHEMA_UNSUPPORTED, "must be a string", path=path)
        return value

    def _decimal(self, value: object, path: str) -> Decimal:
        if not isinstance(value, str):
            self._fail(OnlyScenarioErrorCode.SCENARIO_DECIMAL_INVALID, path, "must be a quoted Decimal string")
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise OnlyScenarioError(OnlyScenarioErrorCode.SCENARIO_DECIMAL_INVALID, str(value), path=path) from exc

    def _timestamp(self, value: object, path: str) -> datetime:
        if not isinstance(value, str):
            self._fail(OnlyScenarioErrorCode.SCENARIO_TIMESTAMP_INVALID, path, "must be ISO-8601 string")
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OnlyScenarioError(OnlyScenarioErrorCode.SCENARIO_TIMESTAMP_INVALID, value, path=path) from exc
        offset = result.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            self._fail(OnlyScenarioErrorCode.SCENARIO_TIMESTAMP_INVALID, path, "must be UTC")
        return result

    def _optional_timestamp(self, value: object, path: str) -> datetime | None:
        return None if value is None else self._timestamp(value, path)

    def _integer(self, value: object, path: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            self._fail(OnlyScenarioErrorCode.SCENARIO_SCHEMA_UNSUPPORTED, path, "must be integer")
        return value

    def _optional_integer(self, value: object, path: str) -> int | None:
        return None if value is None else self._integer(value, path)

    def _enum(self, enum_type: type[OnlyScenarioEnumT], value: object, path: str) -> OnlyScenarioEnumT:
        try:
            return enum_type(self._string(value, path))
        except ValueError as exc:
            raise OnlyScenarioError(OnlyScenarioErrorCode.SCENARIO_SCHEMA_UNSUPPORTED, str(value), path=path) from exc

    @staticmethod
    def _fail(code: OnlyScenarioErrorCode, path: str, message: str) -> NoReturn:
        raise OnlyScenarioError(code, message, path=path)
