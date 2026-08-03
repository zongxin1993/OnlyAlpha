from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.identifiers import OnlyStrategyId


@dataclass(frozen=True, slots=True)
class OnlyFirstBarIntentStrategyConfig(OnlyStrategyConfig):
    cluster_id: OnlyClusterId | None = None
    account_id: OnlyAccountId | None = None
    instrument_id: OnlyInstrumentId | None = None
    quantity: OnlyQuantity | None = None

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> OnlyFirstBarIntentStrategyConfig:
        instruments = values.get("instruments")
        configured_instrument = values.get("instrument_id")
        if not isinstance(instruments, Mapping) or not isinstance(configured_instrument, str):
            raise TypeError("First Bar Intent Strategy requires instrument references")
        instrument_id = next((item for item in instruments if str(item) == configured_instrument), None)
        if not isinstance(instrument_id, OnlyInstrumentId):
            raise ValueError(f"unknown instrument_id: {configured_instrument}")
        instrument = instruments[instrument_id]
        return cls(
            OnlyStrategyId(str(values.get("strategy_id", "first-bar-intent"))),
            (),
            {},
            OnlyClusterId(str(values["cluster_id"])),
            OnlyAccountId(str(values["account_id"])),
            instrument_id,
            OnlyQuantity(Decimal(str(values.get("quantity", "100"))), instrument.quantity_precision),
        )
