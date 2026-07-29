"""Explicit Runtime checkpoint participant contracts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .codec import only_create_checkpoint_component, only_decode_checkpoint_component
from .model import (
    OnlyCheckpointCapability,
    OnlyCheckpointCaptureContext,
    OnlyCheckpointRestoreContext,
    OnlyRuntimeCheckpointComponent,
)


class OnlyRuntimeCheckpointParticipant(Protocol):
    @property
    def checkpoint_component_id(self) -> str: ...

    @property
    def checkpoint_schema_version(self) -> int: ...

    @property
    def checkpoint_capability(self) -> OnlyCheckpointCapability: ...

    def capture_checkpoint(self, context: OnlyCheckpointCaptureContext) -> OnlyRuntimeCheckpointComponent: ...

    def restore_checkpoint(
        self,
        component: OnlyRuntimeCheckpointComponent,
        context: OnlyCheckpointRestoreContext,
    ) -> None: ...


class OnlyJsonRuntimeCheckpointParticipant:
    """Explicit adapter for a component-owned canonical JSON snapshot contract."""

    def __init__(
        self,
        component_id: str,
        schema_version: int,
        capture: Callable[[], object],
        restore: Callable[[object], None],
    ) -> None:
        self._component_id = component_id
        self._schema_version = schema_version
        self._capture = capture
        self._restore = restore

    @property
    def checkpoint_component_id(self) -> str:
        return self._component_id

    @property
    def checkpoint_schema_version(self) -> int:
        return self._schema_version

    @property
    def checkpoint_capability(self) -> OnlyCheckpointCapability:
        return OnlyCheckpointCapability.CHECKPOINTABLE

    def capture_checkpoint(self, context: OnlyCheckpointCaptureContext) -> OnlyRuntimeCheckpointComponent:
        del context
        return only_create_checkpoint_component(
            self._component_id,
            self._schema_version,
            self._capture(),
        )

    def restore_checkpoint(
        self,
        component: OnlyRuntimeCheckpointComponent,
        context: OnlyCheckpointRestoreContext,
    ) -> None:
        del context
        if component.component_id != self._component_id or component.component_schema_version != self._schema_version:
            raise ValueError(f"checkpoint component contract mismatch: {self._component_id}")
        self._restore(only_decode_checkpoint_component(component))


class OnlyStatelessRuntimeCheckpointParticipant:
    def __init__(self, component_id: str) -> None:
        self._component_id = component_id

    @property
    def checkpoint_component_id(self) -> str:
        return self._component_id

    @property
    def checkpoint_schema_version(self) -> int:
        return 1

    @property
    def checkpoint_capability(self) -> OnlyCheckpointCapability:
        return OnlyCheckpointCapability.STATELESS

    def capture_checkpoint(self, context: OnlyCheckpointCaptureContext) -> OnlyRuntimeCheckpointComponent:
        del context
        raise RuntimeError("stateless checkpoint participants are not captured")

    def restore_checkpoint(
        self,
        component: OnlyRuntimeCheckpointComponent,
        context: OnlyCheckpointRestoreContext,
    ) -> None:
        del component, context
        raise RuntimeError("stateless checkpoint participants are not restored")
