from __future__ import annotations

import os
from pathlib import Path

import pytest

from onlyalpha.persistence.postgres.credentials import (
    MASTER_KEY_BYTES,
    MASTER_KEY_VERSION,
    OnlyCredentialError,
    OnlyCredentialMetadata,
    OnlyPostgresCredentialAuthority,
    only_ensure_dev_master_key,
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


def test_credential_ciphertext_is_bound_to_exact_slot_generation_and_key_version() -> None:
    authority = _authority()
    credential_id = "ba13b6b1-af9a-450f-833d-48f5002297dc"
    ciphertext = authority._encrypt(
        credential_id,
        "INTEGRATION_SECRET",
        "b52eb762-34cf-47d4-8cca-56ef93f0d2ac",
        "api_key",
        2,
        MASTER_KEY_VERSION,
        "secret-value",
    )

    assert b"secret-value" not in ciphertext
    assert (
        authority._decrypt(
            credential_id,
            "INTEGRATION_SECRET",
            "b52eb762-34cf-47d4-8cca-56ef93f0d2ac",
            "api_key",
            2,
            MASTER_KEY_VERSION,
            ciphertext,
        )
        == "secret-value"
    )
    for secret_name, generation, key_version in (
        ("api_secret", 2, MASTER_KEY_VERSION),
        ("api_key", 3, MASTER_KEY_VERSION),
        ("api_key", 2, MASTER_KEY_VERSION + 1),
    ):
        with pytest.raises(OnlyCredentialError) as raised:
            authority._decrypt(
                credential_id,
                "INTEGRATION_SECRET",
                "b52eb762-34cf-47d4-8cca-56ef93f0d2ac",
                secret_name,
                generation,
                key_version,
                ciphertext,
            )
        assert raised.value.code == "CREDENTIAL_CIPHERTEXT_INVALID"


def test_credential_metadata_has_no_plaintext_or_masked_secret_surface() -> None:
    assert set(OnlyCredentialMetadata.__dataclass_fields__) == {
        "credential_id",
        "credential_kind",
        "subject_id",
        "secret_name",
        "generation",
        "key_version",
        "created_at",
        "updated_at",
        "configured",
    }


def test_credential_slot_rejects_noncanonical_secret_name_before_persistence() -> None:
    with pytest.raises(OnlyCredentialError) as raised:
        _authority().create("INTEGRATION_SECRET", "integration-id", "Api-Key", "secret")

    assert raised.value.code == "CREDENTIAL_SLOT_INVALID"


def test_dev_master_key_rejects_invalid_existing_key(tmp_path: Path) -> None:
    path = tmp_path / "dev-master-key"
    path.write_bytes(b"short")

    with pytest.raises(ValueError, match="CREDENTIAL_MASTER_KEY_INVALID"):
        only_ensure_dev_master_key(path)
