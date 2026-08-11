"""Market-neutral configuration envelope passed to a selected product factory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.market.product.identity import (
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductVersion,
)

type OnlyMarketProductConfigScalar = str | int | float | bool | None
type OnlyMarketProductConfigValue = (
    OnlyMarketProductConfigScalar
    | tuple[OnlyMarketProductConfigValue, ...]
    | Mapping[str, OnlyMarketProductConfigValue]
)


def _freeze(value: object) -> OnlyMarketProductConfigValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Market Product config keys must be strings")
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    raise TypeError(f"unsupported Market Product config value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class OnlyCanonicalMarketProductConfig:
    """Immutable transport payload; only the selected plugin interprets its keys."""

    values: Mapping[str, OnlyMarketProductConfigValue] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        frozen = _freeze(self.values)
        if not isinstance(frozen, Mapping):
            raise TypeError("Market Product config payload must be a mapping")
        object.__setattr__(self, "values", frozen)

    @property
    def fingerprint(self) -> str:
        """Transport identity only; factories must not reuse this as economic identity blindly."""

        return only_canonical_fingerprint(self.values)


@dataclass(frozen=True, slots=True)
class OnlyMarketProductConfig:
    plugin_id: OnlyMarketProductPluginId
    product_id: OnlyMarketProductId
    product_version: OnlyMarketProductVersion
    config: OnlyCanonicalMarketProductConfig = field(default_factory=OnlyCanonicalMarketProductConfig)


__all__ = [name for name in globals() if name.startswith("Only")]
