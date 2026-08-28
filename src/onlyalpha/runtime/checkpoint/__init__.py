"""Public Runtime checkpoint infrastructure."""

from importlib import import_module as _import_module

from .codec import (
    only_canonical_checkpoint_payload,
    only_checkpoint_payload_hash,
    only_create_checkpoint_component,
    only_decode_checkpoint_component,
    only_runtime_checkpoint_hash,
    only_seal_runtime_checkpoint,
    only_validate_runtime_checkpoint,
)
from .model import (
    ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
    OnlyCheckpointCapability,
    OnlyCheckpointCaptureContext,
    OnlyCheckpointRestoreContext,
    OnlyRuntimeCheckpoint,
    OnlyRuntimeCheckpointComponent,
    OnlyRuntimeCheckpointHeader,
)
from .participant import (
    OnlyJsonRuntimeCheckpointParticipant,
    OnlyRuntimeCheckpointParticipant,
    OnlyStatelessRuntimeCheckpointParticipant,
)
from .registry import OnlyRuntimeCheckpointParticipantRegistry

__all__ = [
    "ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION",
    "OnlyCheckpointCapability",
    "OnlyCheckpointCaptureContext",
    "OnlyCheckpointRestoreContext",
    "OnlyJsonRuntimeCheckpointParticipant",
    "OnlyRuntimeCheckpoint",
    "OnlyRuntimeCheckpointComponent",
    "OnlyRuntimeCheckpointHeader",
    "OnlyRuntimeCheckpointParticipant",
    "OnlyRuntimeCheckpointParticipantRegistry",
    "OnlyRuntimeCheckpointService",
    "OnlyStatelessRuntimeCheckpointParticipant",
    "only_canonical_checkpoint_payload",
    "only_checkpoint_payload_hash",
    "only_create_checkpoint_component",
    "only_decode_checkpoint_component",
    "only_runtime_checkpoint_hash",
    "only_seal_runtime_checkpoint",
    "only_validate_runtime_checkpoint",
]

_LAZY_EXPORTS = {"OnlyRuntimeCheckpointService": "onlyalpha.runtime.checkpoint.service"}


def __getattr__(name: str) -> object:
    try:
        module_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value: object = getattr(_import_module(module_name), name)
    globals()[name] = value
    return value
