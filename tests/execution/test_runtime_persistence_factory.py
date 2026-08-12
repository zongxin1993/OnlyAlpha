from pathlib import Path

from onlyalpha.config import (
    OnlyRuntimeCheckpointConfig,
    OnlyRuntimePersistenceBackend,
    OnlyRuntimePersistenceConfig,
)
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore, OnlySqliteRuntimePersistenceStore


def _request(root: Path, config: OnlyRuntimePersistenceConfig) -> OnlyRuntimePersistenceStoreCreateRequest:
    return OnlyRuntimePersistenceStoreCreateRequest(
        OnlyEngineId("engine"),
        OnlyRuntimeId("runtime"),
        OnlyRuntimeMode.BACKTEST,
        config,
        root,
        "fingerprint",
        "participant-fingerprint",
        "CNY",
        OnlyAccountId("account"),
        "GENERIC_T0_CASH",
    )


def test_memory_persistence_factory_has_no_filesystem_side_effect(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    store = OnlyDefaultRuntimePersistenceStoreFactory().create(_request(state_root, OnlyRuntimePersistenceConfig()))
    assert isinstance(store, OnlyInMemoryRuntimePersistenceStore)
    assert not state_root.exists()
    store.close()


def test_sqlite_factory_creates_stable_default_and_explicit_paths(tmp_path: Path) -> None:
    factory = OnlyDefaultRuntimePersistenceStoreFactory()
    checkpoint = OnlyRuntimeCheckpointConfig(enabled=True)
    default = factory.create(
        _request(
            tmp_path / "default",
            OnlyRuntimePersistenceConfig(OnlyRuntimePersistenceBackend.SQLITE),
        )
    )
    assert isinstance(default, OnlySqliteRuntimePersistenceStore)
    assert (tmp_path / "default" / "runtime.sqlite3").is_file()
    default.close()

    explicit = factory.create(
        _request(
            tmp_path / "explicit",
            OnlyRuntimePersistenceConfig(
                OnlyRuntimePersistenceBackend.SQLITE,
                "nested/store.sqlite3",
                checkpoint,
            ),
        )
    )
    assert isinstance(explicit, OnlySqliteRuntimePersistenceStore)
    assert (tmp_path / "explicit" / "nested" / "store.sqlite3").is_file()
    explicit.close()


def test_sqlite_durable_transactions_do_not_require_checkpoint_enablement() -> None:
    config = OnlyRuntimePersistenceConfig(OnlyRuntimePersistenceBackend.SQLITE)

    assert config.checkpoint.enabled is False


def test_validate_does_not_create_state_directory(tmp_path: Path) -> None:
    config = OnlyRuntimePersistenceConfig(
        OnlyRuntimePersistenceBackend.SQLITE,
        checkpoint=OnlyRuntimeCheckpointConfig(enabled=True),
    )
    OnlyDefaultRuntimePersistenceStoreFactory().validate(config)
    assert tuple(tmp_path.iterdir()) == ()
