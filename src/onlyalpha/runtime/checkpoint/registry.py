"""Stable participant ordering, validation, and fingerprinting."""

from __future__ import annotations

import hashlib
import json

from .model import (
    OnlyCheckpointCapability,
    OnlyCheckpointCaptureContext,
    OnlyCheckpointRestoreContext,
    OnlyRuntimeCheckpointComponent,
)
from .participant import OnlyRuntimeCheckpointParticipant


class OnlyRuntimeCheckpointParticipantRegistry:
    def __init__(self) -> None:
        self._participants: dict[str, OnlyRuntimeCheckpointParticipant] = {}

    def register(self, participant: OnlyRuntimeCheckpointParticipant) -> None:
        component_id = participant.checkpoint_component_id
        if not component_id.strip():
            raise ValueError("checkpoint participant component id is required")
        if component_id in self._participants:
            raise ValueError(f"duplicate checkpoint participant: {component_id}")
        if not isinstance(participant.checkpoint_capability, OnlyCheckpointCapability):
            raise ValueError(f"checkpoint capability is not declared: {component_id}")
        self._participants[component_id] = participant

    @property
    def participants(self) -> tuple[OnlyRuntimeCheckpointParticipant, ...]:
        return tuple(self._participants[key] for key in sorted(self._participants))

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            [
                (
                    item.checkpoint_component_id,
                    item.checkpoint_schema_version,
                    item.checkpoint_capability.value,
                )
                for item in self.participants
            ],
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def capture(self, context: OnlyCheckpointCaptureContext) -> tuple[OnlyRuntimeCheckpointComponent, ...]:
        return tuple(
            item.capture_checkpoint(context)
            for item in self.participants
            if item.checkpoint_capability is OnlyCheckpointCapability.CHECKPOINTABLE
        )

    def validate_components(self, components: tuple[OnlyRuntimeCheckpointComponent, ...]) -> None:
        expected = {
            item.checkpoint_component_id: item.checkpoint_schema_version
            for item in self.participants
            if item.checkpoint_capability is OnlyCheckpointCapability.CHECKPOINTABLE
        }
        actual = {item.component_id: item.component_schema_version for item in components}
        if len(actual) != len(components):
            raise ValueError("checkpoint contains duplicate components")
        missing = sorted(set(expected) - set(actual))
        unknown = sorted(set(actual) - set(expected))
        if missing:
            raise ValueError(f"checkpoint component missing: {missing[0]}")
        if unknown:
            raise ValueError(f"checkpoint component unsupported: {unknown[0]}")
        mismatched = sorted(key for key in expected if expected[key] != actual[key])
        if mismatched:
            raise ValueError(f"checkpoint component schema unsupported: {mismatched[0]}")

    def restore(
        self,
        components: tuple[OnlyRuntimeCheckpointComponent, ...],
        context: OnlyCheckpointRestoreContext,
    ) -> None:
        self.validate_components(components)
        by_id = {item.component_id: item for item in components}
        for participant in self.participants:
            if participant.checkpoint_capability is OnlyCheckpointCapability.CHECKPOINTABLE:
                participant.restore_checkpoint(by_id[participant.checkpoint_component_id], context)
