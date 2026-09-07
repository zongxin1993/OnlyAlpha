"""Stable fail-closed symbolic-search failures."""

from __future__ import annotations


class OnlySymbolicSearchError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class OnlySymbolicSearchStoreError(OnlySymbolicSearchError):
    """Immutable symbolic authority persistence failure."""
