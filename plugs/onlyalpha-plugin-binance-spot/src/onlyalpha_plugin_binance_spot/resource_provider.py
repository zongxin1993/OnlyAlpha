"""Verified operator resource document loader for Binance Spot Backtest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from onlyalpha_plugin_binance_spot.reference import OnlyBinanceSpotReferenceAuthority


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotReferenceResourceProvider:
    provider_id: str = "onlyalpha-plugin-binance-spot/reference@1"

    def load_reference(self, payload: Mapping[str, object]) -> OnlyBinanceSpotReferenceAuthority:
        if set(payload) != {"observed_at", "authority"} or not isinstance(payload["authority"], dict):
            raise ValueError("BINANCE_SPOT_RESOURCE_SCHEMA_INVALID")
        observed_at = payload["observed_at"]
        if not isinstance(observed_at, str):
            raise ValueError("BINANCE_SPOT_RESOURCE_OBSERVED_AT_INVALID")
        return OnlyBinanceSpotReferenceAuthority.from_semantic_dict(
            payload["authority"],
            observed_at=datetime.fromisoformat(observed_at),
        )

    def dump_reference(self, authority: OnlyBinanceSpotReferenceAuthority) -> dict[str, object]:
        observed = {item.observed_at for item in authority.references}
        if len(observed) != 1:
            raise ValueError("BINANCE_SPOT_RESOURCE_OBSERVED_AT_AMBIGUOUS")
        return {"observed_at": next(iter(observed)).isoformat(), "authority": authority.to_semantic_dict()}


__all__ = ["OnlyBinanceSpotReferenceResourceProvider"]
