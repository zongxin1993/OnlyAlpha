"""Built-in Scenario Strategy; commands enter the kernel only through ``ctx.orders``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import cast

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyOrderId, OnlyOrderRequestId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.factor.base import OnlyTimeSeriesFactor
from onlyalpha.factor.config import OnlyFactorConfig, OnlyFactorType
from onlyalpha.factor.context import OnlyFactorBarContext
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.score import OnlyFactorScore, OnlyFactorScoreDimension
from onlyalpha.factor.snapshot import OnlyFactorSnapshot
from onlyalpha.order.views import OnlyOrderServiceView
from onlyalpha.runtime.context import OnlyInstrumentView
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext
from onlyalpha.strategy.identifiers import OnlyStrategyId


@dataclass(frozen=True, slots=True)
class OnlyScenarioBarFactorSnapshot(OnlyFactorSnapshot):
    factor_id: OnlyFactorId
    ready: bool
    ts_event: OnlyTimestamp | None

    def to_dict(self) -> Mapping[str, object]:
        return {"factor_id": str(self.factor_id), "ready": self.ready}


class OnlyScenarioBarFactorConfig(OnlyFactorConfig):
    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> OnlyScenarioBarFactorConfig:
        return cls(OnlyFactorId(str(raw["factor_id"])), OnlyFactorType.TIME_SERIES)


class OnlyScenarioBarFactor(OnlyTimeSeriesFactor):
    def __init__(self, config: OnlyScenarioBarFactorConfig) -> None:
        super().__init__(config)
        self._timestamp: OnlyTimestamp | None = None

    def on_initialize(self) -> None:
        return None

    def on_bar(self, context: OnlyFactorBarContext) -> None:
        self._timestamp = OnlyTimestamp.from_datetime(context.bar.ts_event)

    def snapshot(self) -> OnlyScenarioBarFactorSnapshot:
        return OnlyScenarioBarFactorSnapshot(self.factor_id, True, self._timestamp)

    def score(self) -> OnlyFactorScore:
        return OnlyFactorScore(
            self.factor_id, Decimal(0), OnlyFactorScoreDimension.CUSTOM, Decimal(1), True, self._timestamp
        )


@dataclass(frozen=True, slots=True)
class OnlyScenarioActionStrategyConfig(OnlyStrategyConfig):
    actions: tuple[Mapping[str, object], ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> OnlyScenarioActionStrategyConfig:
        actions_raw = raw.get("actions", [])
        if not isinstance(actions_raw, list) or any(not isinstance(item, Mapping) for item in actions_raw):
            raise ValueError("Scenario Strategy actions must be an array")
        factor_id = OnlyFactorId(str(raw["factor_id"]))
        return cls(
            OnlyStrategyId(str(raw.get("strategy_id", "scenario-action-strategy"))),
            (factor_id,),
            MappingProxyType({}),
            tuple(MappingProxyType(dict(item)) for item in actions_raw),
        )


class OnlyScenarioActionStrategy(OnlyStrategy):
    def __init__(self, config: OnlyScenarioActionStrategyConfig) -> None:
        super().__init__(config)
        self._bar_sequence = 0
        self._orders: dict[str, OnlyOrderId] = {}
        self._records: list[dict[str, object]] = []

    @property
    def scenario_config(self) -> OnlyScenarioActionStrategyConfig:
        return self.config  # type: ignore[return-value]

    def on_initialize(self) -> None:
        return None

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        self._bar_sequence += 1
        orders = cast(OnlyOrderServiceView, context.strategy.orders)
        instruments = cast(OnlyInstrumentView, context.strategy.instruments)
        for action in self.scenario_config.actions:
            if int(str(action["sequence"])) != self._bar_sequence:
                continue
            action_id = str(action["action_id"])
            if action["type"] == "CANCEL_ORDER":
                cancel_result = orders.cancel(self._orders[str(action["target_action_id"])])
                self._records.append({"action_id": action_id, "status": "EXECUTED", "changed": cancel_result.requested})
                continue
            instrument_id = OnlyInstrumentId.parse(str(action["instrument_id"]))
            instrument = cast(OnlyInstrument, instruments.require(instrument_id))
            price_raw = action.get("price")
            request = OnlyOrderRequest(
                OnlyOrderRequestId(f"scenario-{action_id}"),
                instrument_id,
                OnlyOrderSide(str(action["side"])),
                OnlyOrderType(str(action["order_type"])),
                OnlyQuantity(Decimal(str(action["quantity"])), instrument.quantity_precision),
                OnlyTimeInForce(str(action.get("time_in_force", "DAY"))),
                offset=OnlyOffset(str(action.get("offset", "NONE"))),
                price=None if price_raw is None else OnlyPrice(Decimal(str(price_raw)), instrument.price_precision),
                metadata={"scenario_action_id": action_id},
            )
            submit_result = orders.submit(request)
            if submit_result.order_id is not None:
                self._orders[action_id] = submit_result.order_id
            self._records.append(
                {
                    "action_id": action_id,
                    "status": "EXECUTED" if submit_result.created else "REJECTED",
                    "order_id": str(submit_result.order_id or ""),
                    "error": submit_result.error or "",
                    "risk_rejection": ""
                    if submit_result.risk_rejection is None
                    else submit_result.risk_rejection.message,
                }
            )

    def build_result_extension(self) -> Mapping[str, object]:
        return {"scenario_actions": tuple(self._records)}
