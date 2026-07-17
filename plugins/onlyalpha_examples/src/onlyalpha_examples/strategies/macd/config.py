from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.identifiers import OnlyStrategyId


@dataclass(frozen=True, slots=True)
class OnlyMacdStrategyConfig(OnlyStrategyConfig):
    cluster_id: OnlyClusterId | None = None
    account_id: OnlyAccountId | None = None
    instrument_id: OnlyInstrumentId | None = None
    trade_quantity: OnlyQuantity | None = None
    allow_reentry: bool = False
    exit_mode: str = "FULL_AVAILABLE"

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> OnlyMacdStrategyConfig:
        cluster_id = values["cluster_id"]
        account_id = values["account_id"]
        factor_id = OnlyFactorId(str(values.get("signal_factor_id", "macd-signal")))
        instrument_value = values.get("instrument_id")
        instruments = values.get("instruments")
        if not isinstance(instrument_value, str) or not isinstance(instruments, Mapping):
            raise TypeError("MACD Strategy requires instrument_id and reference instruments")
        instrument_id = next((item for item in instruments if str(item) == instrument_value), None)
        if not isinstance(instrument_id, OnlyInstrumentId):
            raise ValueError(f"unknown MACD instrument_id: {instrument_value}")
        instrument = instruments[instrument_id]
        precision = instrument.quantity_precision
        quantity = OnlyQuantity(Decimal(str(values.get("trade_quantity", "100"))), precision)
        return cls(
            OnlyStrategyId(str(values.get("strategy_id", "macd-strategy"))),
            (factor_id,),
            {},
            cluster_id if isinstance(cluster_id, OnlyClusterId) else OnlyClusterId(str(cluster_id)),
            account_id if isinstance(account_id, OnlyAccountId) else OnlyAccountId(str(account_id)),
            instrument_id,
            quantity,
            bool(values.get("allow_reentry", False)),
            str(values.get("exit_mode", "FULL_AVAILABLE")),
        )
