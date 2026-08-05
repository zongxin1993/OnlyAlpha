from pathlib import Path

import pytest

from onlyalpha.execution import OnlyRuntimeProjectionComponent
from onlyalpha.runtime.persistence.store import (
    OnlyInMemoryRuntimePersistenceStore,
    OnlySqliteRuntimePersistenceStore,
)
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction


@pytest.mark.parametrize("backend", ("memory", "sqlite"))
def test_order_fee_accrual_projection_round_trips_through_runtime_store(backend: str, tmp_path: Path) -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = (
        OnlyInMemoryRuntimePersistenceStore()
        if backend == "memory"
        else OnlySqliteRuntimePersistenceStore(tmp_path / "order-fee.sqlite3")
    )
    expected = store.commit(prepared, committed_at=prepared.prepared_at).transaction
    if isinstance(store, OnlySqliteRuntimePersistenceStore):
        store.close()
        store = OnlySqliteRuntimePersistenceStore(tmp_path / "order-fee.sqlite3")
    actual = store.get_by_sequence(prepared.runtime_id, 1)
    assert actual == expected
    assert actual is not None
    assert any(
        item.identity.component is OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL for item in actual.projections
    )
    if isinstance(store, OnlySqliteRuntimePersistenceStore):
        store.close()
