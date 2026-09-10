"""Stable fail-closed errors for immutable Agent decision context."""

from __future__ import annotations


class OnlyAgentContextError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class OnlyAgentContextStoreError(OnlyAgentContextError):
    """Durable immutable-context persistence failure."""


__all__ = ["OnlyAgentContextError", "OnlyAgentContextStoreError"]
