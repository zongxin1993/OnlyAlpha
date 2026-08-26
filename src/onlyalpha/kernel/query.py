"""Deterministic transport-neutral read-only Product Query dispatch boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


class OnlyProductQuery:
    """Marker for immutable, explicitly typed Product observation intent."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class OnlyProductQueryBinding[QueryT: OnlyProductQuery, ResultT]:
    query_type: type[QueryT]
    handler: Callable[[QueryT], ResultT]

    def __post_init__(self) -> None:
        if not isinstance(self.query_type, type) or not issubclass(self.query_type, OnlyProductQuery):
            raise TypeError("Product Query binding type must derive from OnlyProductQuery")
        if not callable(self.handler):
            raise TypeError("Product Query binding handler must be callable")


class OnlyProductQueryError(RuntimeError):
    """A Product Query could not cross the typed dispatch boundary."""


class OnlyUnsupportedProductQuery(OnlyProductQueryError):
    def __init__(self, query_type: type[object]) -> None:
        super().__init__(f"Unsupported Product Query exact type: {query_type.__module__}.{query_type.__qualname__}")


class OnlyDuplicateProductQueryBinding(OnlyProductQueryError):
    def __init__(self, query_type: type[OnlyProductQuery]) -> None:
        super().__init__(
            f"Duplicate Product Query binding for exact type: {query_type.__module__}.{query_type.__qualname__}"
        )


class OnlyProductQueryDispatcher:
    """Invoke one read-only handler selected by exact Query type."""

    def __init__(self, bindings: tuple[OnlyProductQueryBinding[Any, Any], ...]) -> None:
        if not isinstance(bindings, tuple):
            raise TypeError("Product Query bindings must be an explicitly frozen tuple")
        handlers: dict[type[OnlyProductQuery], Callable[[Any], object]] = {}
        for binding in bindings:
            if not isinstance(binding, OnlyProductQueryBinding):
                raise TypeError("Product Query bindings must contain OnlyProductQueryBinding values")
            if binding.query_type in handlers:
                raise OnlyDuplicateProductQueryBinding(binding.query_type)
            handlers[binding.query_type] = binding.handler
        self._handlers = MappingProxyType(handlers)

    def dispatch(self, query: OnlyProductQuery) -> object:
        handler = self._handlers.get(type(query))
        if handler is None:
            raise OnlyUnsupportedProductQuery(type(query))
        return handler(query)


__all__ = [name for name in globals() if name.startswith("Only")]
