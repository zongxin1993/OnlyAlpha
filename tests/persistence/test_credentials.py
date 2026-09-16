from __future__ import annotations

import os
from pathlib import Path

import pytest

from onlyalpha.persistence.postgres.credentials import (
    MASTER_KEY_BYTES,
    OnlyPostgresCredentialAuthority,
    only_ensure_dev_master_key,
    only_mask_credential,
)


def _authority() -> OnlyPostgresCredentialAuthority:
    return OnlyPostgresCredentialAuthority("postgresql://unused/onlyalpha", b"k" * MASTER_KEY_BYTES)


def test_dev_master_key_is_durable_and_not_replaced(tmp_path: Path) -> None:
    path = tmp_path / "user-data" / "secrets" / "dev-master-key"

    first = only_ensure_dev_master_key(path)
    second = only_ensure_dev_master_key(path)

    assert len(first) == MASTER_KEY_BYTES
    assert second == first
    assert path.read_bytes() == first
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_credential_ciphertext_round_trips_and_rejects_context_or_tampering() -> None:
    authority = _authority()
    ciphertext = authority._encrypt("BROKER", "demo", "secret-value")

    assert b"secret-value" not in ciphertext
    assert authority._decrypt("BROKER", "demo", ciphertext) == "secret-value"
    with pytest.raises(ValueError, match="CREDENTIAL_CIPHERTEXT_INVALID"):
        authority._decrypt("BROKER", "other", ciphertext)
    tampered = ciphertext[:-1] + bytes((ciphertext[-1] ^ 1,))
    with pytest.raises(ValueError, match="CREDENTIAL_CIPHERTEXT_INVALID"):
        authority._decrypt("BROKER", "demo", tampered)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (None, "****"),
        ("", "****"),
        ("abc", "****"),
        ("abcd", "****"),
        ("abcdefg", "****"),
        ("abcdefgh", "abc****efgh"),
        ("abcdefghi", "abc****fghi"),
    ),
)
def test_credential_metadata_is_masked(value: str | None, expected: str) -> None:
    assert only_mask_credential(value) == expected


def test_dev_master_key_rejects_invalid_existing_key(tmp_path: Path) -> None:
    path = tmp_path / "dev-master-key"
    path.write_bytes(b"short")

    with pytest.raises(ValueError, match="CREDENTIAL_MASTER_KEY_INVALID"):
        only_ensure_dev_master_key(path)
