"""Versioned immutable Runtime checkpoint contracts."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.plugin.capabilities import OnlyCheckpointCapability as OnlyCheckpointCapability

ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION = 5


@dataclass(frozen=True, slots=True)
class OnlyRuntimeCheckpointComponent:
    component_id: str
    component_schema_version: int
    payload: str
    payload_hash: str

    def __post_init__(self) -> None:
        if not self.component_id.strip() or self.component_schema_version < 1:
            raise ValueError("checkpoint component identity and schema version are required")


@dataclass(frozen=True, slots=True)
class OnlyRuntimeCheckpointHeader:
    runtime_id: OnlyRuntimeId
    checkpoint_sequence: int
    covered_execution_sequence: int
    checkpoint_schema_version: int
    created_at: OnlyTimestamp
    config_fingerprint: str
    market_composition_fingerprint: str
    participant_registry_fingerprint: str
    aggregate_payload_hash: str
    pending_outbox_count: int = 0

    def __post_init__(self) -> None:
        if self.checkpoint_sequence < 1 or self.covered_execution_sequence < 0:
            raise ValueError("invalid checkpoint sequence")
        if self.checkpoint_schema_version != ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("unsupported Runtime checkpoint schema version")
        if self.pending_outbox_count < 0:
            raise ValueError("checkpoint pending outbox count cannot be negative")
        for value in (
            self.config_fingerprint,
            self.market_composition_fingerprint,
            self.participant_registry_fingerprint,
            self.aggregate_payload_hash,
        ):
            if not value:
                raise ValueError("checkpoint fingerprints and hash are required")
        if len(self.market_composition_fingerprint) != 64 or any(
            item not in "0123456789abcdef" for item in self.market_composition_fingerprint
        ):
            raise ValueError("checkpoint Market Product composition fingerprint must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class OnlyRuntimeCheckpoint:
    header: OnlyRuntimeCheckpointHeader
    components: tuple[OnlyRuntimeCheckpointComponent, ...]

    def __post_init__(self) -> None:
        ids = tuple(item.component_id for item in self.components)
        if ids != tuple(sorted(ids)):
            raise ValueError("checkpoint components must use canonical component-id order")
        if len(ids) != len(set(ids)):
            raise ValueError("checkpoint component ids must be unique")


@dataclass(frozen=True, slots=True)
class OnlyCheckpointCaptureContext:
    runtime_id: OnlyRuntimeId
    created_at: OnlyTimestamp
    covered_execution_sequence: int


@dataclass(frozen=True, slots=True)
class OnlyCheckpointRestoreContext:
    runtime_id: OnlyRuntimeId
