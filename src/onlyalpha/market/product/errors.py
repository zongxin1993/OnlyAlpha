"""Fail-closed Market Product composition errors."""

from __future__ import annotations


class OnlyMarketProductError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class OnlyUnknownMarketProductPluginError(OnlyMarketProductError):
    pass


class OnlyDuplicateMarketProductPluginError(OnlyMarketProductError):
    pass


class OnlyUnsupportedMarketProductError(OnlyMarketProductError):
    pass


class OnlyUnsupportedMarketProductVersionError(OnlyMarketProductError):
    pass


class OnlyInvalidMarketProductConfigurationError(OnlyMarketProductError):
    pass


class OnlyMarketProductResolutionError(OnlyMarketProductError):
    pass


class OnlyMarketProductAuthorityConflictError(OnlyMarketProductError):
    pass


__all__ = [name for name in globals() if name.startswith("Only")]
