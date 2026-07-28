from pathlib import Path

from onlyalpha.config import OnlyExecutionStoreBackend, OnlyExecutionStoreConfig
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.execution import OnlyInMemoryExecutionTransactionStore, OnlySqliteExecutionTransactionStore
from onlyalpha.execution.transaction_store_factory import (
    OnlyDefaultExecutionTransactionStoreFactory,
    OnlyExecutionTransactionStoreCreateRequest,
)


def _request(root: Path, config: OnlyExecutionStoreConfig) -> OnlyExecutionTransactionStoreCreateRequest:
    return OnlyExecutionTransactionStoreCreateRequest(
        OnlyEngineId("engine"),
        OnlyRuntimeId("runtime"),
        OnlyRuntimeMode.BACKTEST,
        config,
        root,
        "fingerprint",
        "CNY",
        OnlyAccountId("account"),
        "GENERIC_T0_CASH",
    )


def test_memory_factory_has_no_filesystem_side_effect(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    store = OnlyDefaultExecutionTransactionStoreFactory().create(_request(state_root, OnlyExecutionStoreConfig()))
    assert isinstance(store, OnlyInMemoryExecutionTransactionStore)
    assert not state_root.exists()
    store.close()


def test_sqlite_factory_creates_stable_default_and_explicit_paths(tmp_path: Path) -> None:
    factory = OnlyDefaultExecutionTransactionStoreFactory()
    default = factory.create(_request(tmp_path / "default", OnlyExecutionStoreConfig(OnlyExecutionStoreBackend.SQLITE)))
    assert isinstance(default, OnlySqliteExecutionTransactionStore)
    assert (tmp_path / "default" / "execution.sqlite3").is_file()
    default.close()

    explicit = factory.create(
        _request(
            tmp_path / "explicit",
            OnlyExecutionStoreConfig(OnlyExecutionStoreBackend.SQLITE, "nested/store.sqlite3"),
        )
    )
    assert isinstance(explicit, OnlySqliteExecutionTransactionStore)
    assert (tmp_path / "explicit" / "nested" / "store.sqlite3").is_file()
    explicit.close()


def test_validate_does_not_create_state_directory(tmp_path: Path) -> None:
    config = OnlyExecutionStoreConfig(OnlyExecutionStoreBackend.SQLITE)
    OnlyDefaultExecutionTransactionStoreFactory().validate(config)
    assert tuple(tmp_path.iterdir()) == ()
