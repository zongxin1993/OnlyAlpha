from __future__ import annotations

from dataclasses import replace

from onlyalpha.config import OnlyRuntimePersistenceConfig
from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort


class OnlyBeforeWriteCheckpointStore:
    def __init__(self, delegate: OnlyRuntimePersistenceStorePort) -> None:
        self._delegate = delegate

    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None:
        del checkpoint, retain_last
        raise RuntimeError("TEST_POST_RECOVERY_PRE_WRITE")

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


class OnlyReadBackMismatchCheckpointStore:
    def __init__(self, delegate: OnlyRuntimePersistenceStorePort) -> None:
        self._delegate = delegate
        self._post_recovery_write_completed = False

    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None:
        self._delegate.write_checkpoint(checkpoint, retain_last=retain_last)
        self._post_recovery_write_completed = True

    def latest_checkpoint(self, runtime_id: object) -> OnlyRuntimeCheckpoint | None:
        checkpoint = self._delegate.latest_checkpoint(runtime_id)  # type: ignore[arg-type]
        if checkpoint is None or not self._post_recovery_write_completed:
            return checkpoint
        header = replace(checkpoint.header, aggregate_payload_hash="TEST_READ_BACK_MISMATCH")
        return replace(checkpoint, header=header)

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


class _OnlyCheckpointStoreFactory:
    wrapper: type[OnlyBeforeWriteCheckpointStore] | type[OnlyReadBackMismatchCheckpointStore]

    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyRuntimePersistenceStorePort:
        return self.wrapper(self._delegate.create(request))  # type: ignore[return-value]


class OnlyBeforeWriteCheckpointStoreFactory(_OnlyCheckpointStoreFactory):
    wrapper = OnlyBeforeWriteCheckpointStore


class OnlyReadBackMismatchCheckpointStoreFactory(_OnlyCheckpointStoreFactory):
    wrapper = OnlyReadBackMismatchCheckpointStore


def no_event_type(runtime: object, event_type: str) -> bool:
    event_bus = runtime.event_bus  # type: ignore[attr-defined]
    return all(item.event.event_type.value != event_type for item in event_bus.dispatch_results)
