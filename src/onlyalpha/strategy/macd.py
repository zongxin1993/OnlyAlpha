"""MACD example strategy factory; all MACD-specific parsing stays here."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.indicator.base import OnlyIndicatorId, OnlyIndicatorRegistration, OnlyIndicatorRequirement
from onlyalpha.indicator.macd import OnlyMacdIndicator, OnlyMacdIndicatorConfig
from onlyalpha.strategies.macd import OnlyMacdExampleCluster, OnlyMacdExampleConfig
from onlyalpha.strategy.factory import OnlyStrategyBuildRequest, OnlyStrategyBuildResult


class OnlyMacdStrategyFactory:
    @property
    def factory_id(self) -> str:
        return "MACD_EXAMPLE"

    def create(self, request: OnlyStrategyBuildRequest) -> OnlyStrategyBuildResult:
        common = request.config.common
        subscriptions = common.subscriptions
        if len(subscriptions.instrument_bars) != 1 or subscriptions.universe_bars:
            raise ValueError("first-phase MACD strategy requires one instrument Bar subscription")
        subscription = subscriptions.instrument_bars[0]
        instrument = request.run_config.reference_data.instrument_by_id[subscription.instrument_id]
        bar_type = subscription.bar_specification.to_bar_type(subscription.instrument_id)
        raw = self._mapping(request.config.extensions, "strategy.extensions")
        indicator_raw = self._mapping(raw.get("indicator", {}), "strategy.extensions.indicator")
        trade_raw = self._mapping(raw.get("trade", {}), "strategy.extensions.trade")
        indicator_id = OnlyIndicatorId(str(indicator_raw.get("indicator_id", "macd-primary")))
        fast = self._integer(indicator_raw.get("fast_period", 12), "fast_period")
        slow = self._integer(indicator_raw.get("slow_period", 26), "slow_period")
        signal = self._integer(indicator_raw.get("signal_period", 9), "signal_period")
        warmup = self._integer(indicator_raw.get("warmup_bars", slow + signal - 1), "warmup_bars")
        indicator = OnlyMacdIndicatorConfig(indicator_id, bar_type, fast, slow, signal, "close", warmup)
        strategy = OnlyMacdExampleConfig(
            common.cluster_id,
            common.account_id,
            subscription.instrument_id,
            bar_type,
            indicator_id,
            OnlyQuantity(Decimal(str(trade_raw.get("quantity", "100"))), instrument.quantity_precision),
            warmup,
            bool(trade_raw.get("allow_reentry", False)),
            str(trade_raw.get("exit_mode", "FULL_AVAILABLE")),
        )
        return OnlyStrategyBuildResult(
            OnlyMacdExampleCluster(strategy),
            (OnlyIndicatorRegistration(OnlyMacdIndicator(indicator), OnlyIndicatorRequirement.REQUIRED),),
        )

    @staticmethod
    def _mapping(value: object, path: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise ValueError(f"{path} must be a mapping")
        return value

    @staticmethod
    def _integer(value: object, path: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{path} must be an integer")
        try:
            return int(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path} must be an integer") from exc
