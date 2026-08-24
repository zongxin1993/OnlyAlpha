"""Stable Strategy Product failures."""

from __future__ import annotations


class OnlyStrategyError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


class OnlyStrategyAdmissionError(OnlyStrategyError):
    pass


class OnlyCalculationEquivalenceError(OnlyStrategyError):
    pass


class OnlyStrategyFreezeError(OnlyStrategyError):
    pass


class OnlyStrategyStoreError(OnlyStrategyError):
    pass


class OnlyStrategyResolutionError(OnlyStrategyError):
    pass


class OnlyStrategyPromotionError(OnlyStrategyError):
    pass


__all__ = [name for name in globals() if name.startswith("Only")]
