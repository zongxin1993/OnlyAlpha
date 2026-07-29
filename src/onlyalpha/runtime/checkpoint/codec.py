"""Canonical JSON codecs and SHA-256 hashes for Runtime checkpoints."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.domain.time import OnlyTimestamp

from .model import (
    OnlyBacktestReplayCursor,
    OnlyRuntimeCheckpoint,
    OnlyRuntimeCheckpointComponent,
    OnlyRuntimeCheckpointHeader,
)


def only_canonical_checkpoint_payload(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def only_checkpoint_payload_hash(payload: str) -> str:
    canonical = only_canonical_checkpoint_payload(json.loads(payload))
    if canonical != payload:
        raise ValueError("checkpoint component payload is not canonical JSON")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def only_create_checkpoint_component(
    component_id: str, component_schema_version: int, value: object
) -> OnlyRuntimeCheckpointComponent:
    payload = only_canonical_checkpoint_payload(value)
    return OnlyRuntimeCheckpointComponent(
        component_id,
        component_schema_version,
        payload,
        only_checkpoint_payload_hash(payload),
    )


def only_decode_checkpoint_component(component: OnlyRuntimeCheckpointComponent) -> object:
    if only_checkpoint_payload_hash(component.payload) != component.payload_hash:
        raise ValueError(f"checkpoint component hash mismatch: {component.component_id}")
    return json.loads(component.payload)


def only_encode_replay_cursor(cursor: OnlyBacktestReplayCursor) -> str:
    return only_canonical_checkpoint_payload(
        {
            "data_version": str(cursor.data_version),
            "last_event_time_ns": None if cursor.last_event_time is None else cursor.last_event_time.unix_nanos,
            "last_source_sequence": cursor.last_source_sequence,
            "last_update_id": None if cursor.last_update_id is None else str(cursor.last_update_id),
            "processed_bar_count": cursor.processed_bar_count,
            "source_id": str(cursor.source_id),
        }
    )


def only_decode_replay_cursor(payload: str) -> OnlyBacktestReplayCursor:
    value = json.loads(payload)
    if not isinstance(value, Mapping) or only_canonical_checkpoint_payload(value) != payload:
        raise ValueError("replay cursor payload is not canonical")
    update_id = value["last_update_id"]
    event_ns = value["last_event_time_ns"]
    return OnlyBacktestReplayCursor(
        OnlyMarketDataSourceId(str(value["source_id"])),
        OnlyDataVersion(str(value["data_version"])),
        None if update_id is None else OnlyMarketDataUpdateId(str(update_id)),
        int(value["last_source_sequence"]),
        None if event_ns is None else OnlyTimestamp.from_unix_nanos(int(event_ns)),
        int(value["processed_bar_count"]),
    )


def _aggregate_projection(
    header: OnlyRuntimeCheckpointHeader,
    components: tuple[OnlyRuntimeCheckpointComponent, ...],
) -> dict[str, object]:
    return {
        "header": {
            "checkpoint_schema_version": header.checkpoint_schema_version,
            "checkpoint_sequence": header.checkpoint_sequence,
            "config_fingerprint": header.config_fingerprint,
            "covered_execution_sequence": header.covered_execution_sequence,
            "created_at_ns": header.created_at.unix_nanos,
            "participant_registry_fingerprint": header.participant_registry_fingerprint,
            "pending_outbox_count": header.pending_outbox_count,
            "replay_cursor": json.loads(only_encode_replay_cursor(header.replay_cursor)),
            "runtime_id": str(header.runtime_id),
        },
        "components": [
            {
                "component_id": item.component_id,
                "component_schema_version": item.component_schema_version,
                "payload": item.payload,
                "payload_hash": item.payload_hash,
            }
            for item in components
        ],
    }


def only_runtime_checkpoint_hash(
    header: OnlyRuntimeCheckpointHeader,
    components: tuple[OnlyRuntimeCheckpointComponent, ...],
) -> str:
    payload = only_canonical_checkpoint_payload(_aggregate_projection(header, components))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def only_seal_runtime_checkpoint(
    header: OnlyRuntimeCheckpointHeader,
    components: tuple[OnlyRuntimeCheckpointComponent, ...],
) -> OnlyRuntimeCheckpoint:
    ordered = tuple(sorted(components, key=lambda item: item.component_id))
    for component in ordered:
        if only_checkpoint_payload_hash(component.payload) != component.payload_hash:
            raise ValueError(f"checkpoint component hash mismatch: {component.component_id}")
    sealed_header = replace(header, aggregate_payload_hash=only_runtime_checkpoint_hash(header, ordered))
    return OnlyRuntimeCheckpoint(sealed_header, ordered)


def only_validate_runtime_checkpoint(checkpoint: OnlyRuntimeCheckpoint) -> None:
    for component in checkpoint.components:
        if only_checkpoint_payload_hash(component.payload) != component.payload_hash:
            raise ValueError(f"checkpoint component hash mismatch: {component.component_id}")
    expected = only_runtime_checkpoint_hash(checkpoint.header, checkpoint.components)
    if expected != checkpoint.header.aggregate_payload_hash:
        raise ValueError("checkpoint aggregate hash mismatch")
