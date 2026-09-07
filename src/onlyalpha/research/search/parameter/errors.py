"""Stable failures for deterministic adaptive parameter search."""

from __future__ import annotations


class OnlyParameterSearchError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class OnlyParameterSearchStoreError(OnlyParameterSearchError):
    """Exact-store, corruption, and frontier conflict failure."""


__all__ = ["OnlyParameterSearchError", "OnlyParameterSearchStoreError"]
