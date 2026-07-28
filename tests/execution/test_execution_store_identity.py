from pathlib import Path

import pytest

from onlyalpha.execution import OnlyExecutionStoreIdentityMismatch, OnlySqliteExecutionTransactionStore


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("runtime_id", "other-runtime"),
        ("engine_id", "other-engine"),
        ("runtime_mode", "LIVE"),
        ("config_fingerprint", "other-fingerprint"),
        ("base_currency", "USD"),
        ("account_id", "other-account"),
        ("market_profile_id", "OTHER_PROFILE"),
    ],
)
def test_reopen_rejects_every_stable_identity_mismatch(tmp_path: Path, field: str, changed: str) -> None:
    path = tmp_path / "execution.sqlite3"
    identity = {
        "runtime_id": "runtime",
        "engine_id": "engine",
        "runtime_mode": "BACKTEST",
        "config_fingerprint": "fingerprint",
        "base_currency": "CNY",
        "account_id": "account",
        "market_profile_id": "GENERIC_T0_CASH",
    }
    store = OnlySqliteExecutionTransactionStore(path, identity=identity)
    store.close()
    changed_identity = dict(identity)
    changed_identity[field] = changed

    with pytest.raises(OnlyExecutionStoreIdentityMismatch, match=field):
        OnlySqliteExecutionTransactionStore(path, identity=changed_identity)

    reopened = OnlySqliteExecutionTransactionStore(path, identity=identity)
    assert reopened.metadata()[field] == identity[field]
    reopened.close()
