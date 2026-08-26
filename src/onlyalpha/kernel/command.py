"""Deterministic transport-neutral Product Command dispatch boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol


class OnlyProductMutationAdmission(Protocol):
    """The one narrow capability required before Product mutation."""

    def assert_mutation_ready(self) -> None: ...


class OnlyProductCommand:
    """Marker for immutable, explicitly typed Product mutation intent."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class OnlyProductCommandBinding[CommandT: OnlyProductCommand, ResultT]:
    command_type: type[CommandT]
    handler: Callable[[CommandT], ResultT]

    def __post_init__(self) -> None:
        if not isinstance(self.command_type, type) or not issubclass(self.command_type, OnlyProductCommand):
            raise TypeError("Product Command binding type must derive from OnlyProductCommand")
        if not callable(self.handler):
            raise TypeError("Product Command binding handler must be callable")


class OnlyProductCommandError(RuntimeError):
    """A Product Command could not cross the typed dispatch boundary."""


class OnlyUnsupportedProductCommand(OnlyProductCommandError):
    def __init__(self, command_type: type[object]) -> None:
        super().__init__(
            f"Unsupported Product Command exact type: {command_type.__module__}.{command_type.__qualname__}"
        )


class OnlyDuplicateProductCommandBinding(OnlyProductCommandError):
    def __init__(self, command_type: type[OnlyProductCommand]) -> None:
        super().__init__(
            f"Duplicate Product Command binding for exact type: {command_type.__module__}.{command_type.__qualname__}"
        )


class OnlyProductCommandDispatcher:
    """Admit READY mutations and invoke one handler by exact Command type."""

    def __init__(
        self,
        admission: OnlyProductMutationAdmission,
        bindings: tuple[OnlyProductCommandBinding[Any, Any], ...],
    ) -> None:
        if not isinstance(bindings, tuple):
            raise TypeError("Product Command bindings must be an explicitly frozen tuple")
        handlers: dict[type[OnlyProductCommand], Callable[[Any], object]] = {}
        for binding in bindings:
            if not isinstance(binding, OnlyProductCommandBinding):
                raise TypeError("Product Command bindings must contain OnlyProductCommandBinding values")
            if binding.command_type in handlers:
                raise OnlyDuplicateProductCommandBinding(binding.command_type)
            handlers[binding.command_type] = binding.handler
        self._admission = admission
        self._handlers = MappingProxyType(handlers)

    def dispatch(self, command: OnlyProductCommand) -> object:
        self._admission.assert_mutation_ready()
        handler = self._handlers.get(type(command))
        if handler is None:
            raise OnlyUnsupportedProductCommand(type(command))
        return handler(command)


__all__ = [name for name in globals() if name.startswith("Only")]
