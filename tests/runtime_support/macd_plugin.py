"""Test-only MACD Strategy/Factor adapter for core vertical-slice tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.factor.base import OnlyTimeSeriesFactor
from onlyalpha.factor.config import OnlyFactorConfig, OnlyFactorType, OnlyIndicatorSpec
from onlyalpha.factor.context import OnlyFactorBarContext
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.score import OnlyFactorQualityFlag, OnlyFactorScore, OnlyFactorScoreDimension
from onlyalpha.factor.snapshot import OnlyFactorSnapshot
from onlyalpha.indicator.macd import OnlyMacdCrossState, OnlyMacdSnapshot
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext
from onlyalpha.strategy.identifiers import OnlyStrategyId


@dataclass(frozen=True, slots=True)
class OnlyTestMacdFactorSnapshot(OnlyFactorSnapshot):
    factor_id: OnlyFactorId
    ts_event: OnlyTimestamp | None
    ready: bool
    signal: str
    trend_score: Decimal
    confidence: Decimal
    macd_snapshot: OnlyMacdSnapshot

    def to_dict(self) -> Mapping[str, object]:
        timestamp = self.macd_snapshot.ts_event
        return {
            "factor_id": str(self.factor_id),
            "ts_event_ns": None if timestamp is None else timestamp.unix_nanos,
            "ready": self.ready,
            "signal": self.signal,
            "trend_score": str(self.trend_score),
            "confidence": str(self.confidence),
            "macd": dict(self.macd_snapshot.to_dict()),
        }


@dataclass(frozen=True, slots=True)
class OnlyTestMacdFactorConfig(OnlyFactorConfig):
    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> OnlyTestMacdFactorConfig:
        raw_specs = values.get("indicator_specs", ())
        if not isinstance(raw_specs, tuple) or len(raw_specs) != 1 or not isinstance(raw_specs[0], Mapping):
            raise ValueError("test MACD Factor requires one indicator")
        raw = raw_specs[0]
        return cls(
            values["factor_id"]
            if isinstance(values["factor_id"], OnlyFactorId)
            else OnlyFactorId(str(values["factor_id"])),
            OnlyFactorType(str(values["factor_type"])),
            (OnlyIndicatorSpec(raw["indicator_id"], raw["indicator_type"], raw["bar_type"], raw["parameters"]),),
            tuple(values.get("dependencies", ())),
            bool(values.get("required", True)),
            {},
        )


class OnlyTestMacdFactor(OnlyTimeSeriesFactor):
    def __init__(self, config: OnlyTestMacdFactorConfig) -> None:
        super().__init__(config)
        self.config = config
        self._indicator_id = config.indicators[0].indicator_id
        self._snapshot = OnlyTestMacdFactorSnapshot(
            config.factor_id,
            None,
            False,
            "WARMING_UP",
            Decimal(0),
            Decimal(0),
            OnlyMacdSnapshot.empty(self._indicator_id),
        )

    def on_initialize(self) -> None:
        spec = self.config.indicators[0]
        self.context.indicators.create_for_bars(
            indicator_type=spec.indicator_type,
            indicator_id=spec.indicator_id,
            bar_type=spec.bar_type,
            parameters=spec.parameters,
        )

    def on_bar(self, context: OnlyFactorBarContext) -> None:
        del context
        macd = self.context.indicators.require_snapshot(self._indicator_id, OnlyMacdSnapshot)
        indicator_score = self.context.indicators.score(self._indicator_id)
        score = Decimal(0) if indicator_score is None else indicator_score.value
        confidence = Decimal(0) if indicator_score is None else indicator_score.confidence
        signal = {
            OnlyMacdCrossState.GOLDEN_CROSS: "GOLDEN_CROSS",
            OnlyMacdCrossState.DEATH_CROSS: "DEATH_CROSS",
        }.get(macd.cross_state, "HOLD" if macd.ready else "WARMING_UP")
        self._snapshot = OnlyTestMacdFactorSnapshot(
            self.factor_id,
            macd.ts_event,
            macd.ready,
            signal,
            score,
            confidence,
            macd,
        )

    def snapshot(self) -> OnlyTestMacdFactorSnapshot:
        return self._snapshot

    def score(self) -> OnlyFactorScore:
        flags = frozenset() if self.ready else frozenset({OnlyFactorQualityFlag.WARMING_UP})
        return OnlyFactorScore(
            self.factor_id,
            self._snapshot.trend_score,
            OnlyFactorScoreDimension.MOMENTUM,
            self._snapshot.confidence,
            self.ready,
            self._snapshot.macd_snapshot.ts_event,
            flags,
        )


@dataclass(frozen=True, slots=True)
class OnlyTestMacdStrategyConfig(OnlyStrategyConfig):
    cluster_id: OnlyClusterId | None = None
    account_id: OnlyAccountId | None = None
    instrument_id: OnlyInstrumentId | None = None
    trade_quantity: OnlyQuantity | None = None
    allow_reentry: bool = False
    exit_mode: str = "FULL_AVAILABLE"

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> OnlyTestMacdStrategyConfig:
        instruments = values.get("instruments")
        instrument_value = values.get("instrument_id")
        if not isinstance(instruments, Mapping) or not isinstance(instrument_value, str):
            raise TypeError("test MACD Strategy requires instrument reference data")
        instrument_id = next((item for item in instruments if str(item) == instrument_value), None)
        if not isinstance(instrument_id, OnlyInstrumentId):
            raise ValueError(f"unknown instrument: {instrument_value}")
        instrument = instruments[instrument_id]
        cluster_id = values["cluster_id"]
        account_id = values["account_id"]
        return cls(
            OnlyStrategyId(str(values.get("strategy_id", "test-macd-strategy"))),
            (OnlyFactorId(str(values.get("signal_factor_id", "macd-signal"))),),
            {},
            cluster_id if isinstance(cluster_id, OnlyClusterId) else OnlyClusterId(str(cluster_id)),
            account_id if isinstance(account_id, OnlyAccountId) else OnlyAccountId(str(account_id)),
            instrument_id,
            OnlyQuantity(Decimal(str(values.get("trade_quantity", "100"))), instrument.quantity_precision),
            bool(values.get("allow_reentry", False)),
            str(values.get("exit_mode", "FULL_AVAILABLE")),
        )


class OnlyTestMacdSignalState(StrEnum):
    WARMING_UP = "WARMING_UP"
    FLAT = "FLAT"
    LONG = "LONG"
    WAITING_EXIT_AVAILABILITY = "WAITING_EXIT_AVAILABILITY"


@dataclass(frozen=True, slots=True)
class OnlyTestMacdSignal:
    sequence: int
    signal_type: str
    ts_event: OnlyTimestamp
    dif: str
    dea: str
    order_request_id: OnlyOrderRequestId | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "signal_type": self.signal_type,
            "ts_event_ns": self.ts_event.unix_nanos,
            "dif": self.dif,
            "dea": self.dea,
            "order_request_id": None if self.order_request_id is None else str(self.order_request_id),
        }


class OnlyTestMacdStrategy(OnlyStrategy):
    def __init__(self, config: OnlyTestMacdStrategyConfig) -> None:
        super().__init__(config)
        self.config = config
        self._request_sequence = 0
        self._has_entered = False
        self._exit_pending = False
        self._callback_count = 0
        self._signal_state = OnlyTestMacdSignalState.WARMING_UP
        self._signals: list[OnlyTestMacdSignal] = []

    def on_initialize(self) -> None:
        if self.config.instrument_id is None or self.config.account_id is None or self.config.trade_quantity is None:
            raise ValueError("test MACD Strategy configuration is incomplete")

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        self._callback_count += 1
        factor = context.strategy.factors.require(self.config.required_factor_ids[0], OnlyTestMacdFactorSnapshot)
        instrument_id = self.config.instrument_id
        if instrument_id is None:
            raise RuntimeError("test instrument unavailable")
        allocation = context.strategy.positions.cluster.get(instrument_id)  # type: ignore[union-attr]
        quantity = None if allocation is None else allocation.total_quantity
        available = None if allocation is None else allocation.available_quantity
        has_position = quantity is not None and quantity.value > 0
        has_open_order = bool(context.strategy.orders.list_open())  # type: ignore[union-attr]
        if self._exit_pending and has_position:
            if available is not None and available.value > 0 and not has_open_order:
                self._submit(context, OnlyOrderSide.SELL, available, factor, "PENDING_EXIT")
                self._exit_pending = False
            else:
                self._signal_state = OnlyTestMacdSignalState.WAITING_EXIT_AVAILABILITY
            return
        if (
            factor.signal == "GOLDEN_CROSS"
            and not has_position
            and not has_open_order
            and (self.config.allow_reentry or not self._has_entered)
        ):
            assert self.config.trade_quantity is not None
            self._submit(context, OnlyOrderSide.BUY, self.config.trade_quantity, factor, "GOLDEN_CROSS")
            self._has_entered = True
        elif factor.signal == "DEATH_CROSS" and has_position and not has_open_order:
            if available is not None and available.value > 0:
                self._submit(context, OnlyOrderSide.SELL, available, factor, "DEATH_CROSS")
            else:
                self._exit_pending = True
                self._signal_state = OnlyTestMacdSignalState.WAITING_EXIT_AVAILABILITY
                self._record("DEATH_CROSS_BLOCKED", factor, None)
        else:
            self._signal_state = OnlyTestMacdSignalState.LONG if has_position else OnlyTestMacdSignalState.FLAT

    def _submit(
        self,
        context: OnlyStrategyBarContext,
        side: OnlyOrderSide,
        quantity: OnlyQuantity,
        factor: OnlyTestMacdFactorSnapshot,
        signal_type: str,
    ) -> None:
        self._request_sequence += 1
        cluster_id = self.config.cluster_id
        account_id = self.config.account_id
        instrument_id = self.config.instrument_id
        if cluster_id is None or account_id is None or instrument_id is None:
            raise RuntimeError("test MACD identifiers unavailable")
        request_id = OnlyOrderRequestId(f"{cluster_id}-macd-{self._request_sequence:06d}-{side.value.lower()}")
        context.strategy.orders.submit(  # type: ignore[union-attr]
            OnlyOrderRequest(
                request_id,
                instrument_id,
                side,
                OnlyOrderType.MARKET,
                quantity,
                account_id=account_id,
                offset=OnlyOffset.OPEN if side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
                tags=("MACD", signal_type),
            )
        )
        self._signal_state = OnlyTestMacdSignalState.LONG if side is OnlyOrderSide.BUY else OnlyTestMacdSignalState.FLAT
        self._record(signal_type, factor, request_id)

    def _record(
        self,
        signal_type: str,
        factor: OnlyTestMacdFactorSnapshot,
        request_id: OnlyOrderRequestId | None,
    ) -> None:
        timestamp = factor.ts_event
        if timestamp is None:
            raise RuntimeError("ready test MACD Factor requires ts_event")
        macd = factor.macd_snapshot
        self._signals.append(
            OnlyTestMacdSignal(len(self._signals) + 1, signal_type, timestamp, str(macd.dif), str(macd.dea), request_id)
        )

    def build_result_extension(self) -> dict[str, object]:
        return {
            "signals": [item.to_dict() for item in self._signals],
            "signal_state": self._signal_state.value,
            "callback_count": self._callback_count,
        }
