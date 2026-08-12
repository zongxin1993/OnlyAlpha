from dataclasses import replace

import pytest

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.runtime.checkpoint.registry import OnlyRuntimeCheckpointParticipantRegistry
from onlyalpha.runtime.checkpoint.service import OnlyRuntimeCheckpointService
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore


def _service(store: OnlyInMemoryRuntimePersistenceStore) -> OnlyRuntimeCheckpointService:
    return OnlyRuntimeCheckpointService(
        runtime_id=OnlyRuntimeId("runtime"),
        config_fingerprint="config",
        market_composition_fingerprint="0" * 64,
        registry=OnlyRuntimeCheckpointParticipantRegistry(),
        write_port=store,
        query_port=store,
        transaction_query=store,
        outbox_port=store,
        retain_last=3,
    )


def test_capture_write_and_full_durable_read_back_are_separate() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    service = _service(store)
    captured = service.capture(OnlyTimestamp.from_unix_nanos(1))
    assert store.latest_checkpoint(OnlyRuntimeId("runtime")) is None
    service.write(captured)
    assert service.verify_durable(captured) == captured


def test_verify_rejects_missing_and_header_mismatch() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    service = _service(store)
    captured = service.capture(OnlyTimestamp.from_unix_nanos(1))
    with pytest.raises(RuntimeError, match="NOT_DURABLE"):
        service.verify_durable(captured)
    service.write(captured)
    wrong = replace(captured, header=replace(captured.header, pending_outbox_count=1))
    with pytest.raises(RuntimeError, match="IDENTITY_MISMATCH"):
        service.verify_durable(wrong)


def test_create_verified_returns_the_store_read_back() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    checkpoint = _service(store).create_verified(OnlyTimestamp.from_unix_nanos(1))
    assert store.latest_checkpoint(OnlyRuntimeId("runtime")) == checkpoint
