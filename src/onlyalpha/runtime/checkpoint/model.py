"""Versioned immutable Runtime checkpoint contracts."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.plugin.capabilities import OnlyCheckpointCapability as OnlyCheckpointCapability

ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class OnlyBacktestReplayCursor:
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    last_update_id: OnlyMarketDataUpdateId | None
    last_source_sequence: int
    last_event_time: OnlyTimestamp | None
    processed_bar_count: int

    def __post_init__(self) -> None:
        if self.last_source_sequence < 0 or self.processed_bar_count < 0:
            raise ValueError("replay cursor sequences cannot be negative")
        if (self.last_update_id is None) != (self.last_event_time is None):
            raise ValueError("replay cursor update identity and event time must be both empty or both present")


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
    replay_cursor: OnlyBacktestReplayCursor
    config_fingerprint: str
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
            self.participant_registry_fingerprint,
            self.aggregate_payload_hash,
        ):
            if not value:
                raise ValueError("checkpoint fingerprints and hash are required")


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
    replay_cursor: OnlyBacktestReplayCursor
    covered_execution_sequence: int


@dataclass(frozen=True, slots=True)
class OnlyCheckpointRestoreContext:
    runtime_id: OnlyRuntimeId
    replay_cursor: OnlyBacktestReplayCursor
