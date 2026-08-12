"""Canonical JSON codecs and SHA-256 hashes for Runtime checkpoints."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from .model import (
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
            "market_composition_fingerprint": header.market_composition_fingerprint,
            "participant_registry_fingerprint": header.participant_registry_fingerprint,
            "pending_outbox_count": header.pending_outbox_count,
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
