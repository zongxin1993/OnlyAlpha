from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import psycopg
import pytest

from onlyalpha.persistence.postgres import (
    MASTER_KEY_BYTES,
    OnlyPostgresCredentialAuthority,
)
from onlyalpha.persistence.postgres.credentials import OnlyCredentialError

pytestmark = pytest.mark.postgres


def _authority(dsn: str) -> OnlyPostgresCredentialAuthority:
    return OnlyPostgresCredentialAuthority(dsn, b"k" * MASTER_KEY_BYTES)


def test_named_credential_slots_are_independent_and_metadata_is_secret_free(postgres_dsn: str) -> None:
    authority = _authority(postgres_dsn)
    first_subject = "b52eb762-34cf-47d4-8cca-56ef93f0d2ac"
    second_subject = "672e3601-506f-45ea-ad7e-452e36f548ea"

    first_key = authority.create("INTEGRATION_SECRET", first_subject, "api_key", "first-key")
    first_secret = authority.create("INTEGRATION_SECRET", first_subject, "api_secret", "first-secret")
    second_key = authority.create("INTEGRATION_SECRET", second_subject, "api_key", "second-key")

    assert len({first_key.credential_id, first_secret.credential_id, second_key.credential_id}) == 3
    assert authority.read_secret(first_key.credential_id, 1) == "first-key"
    assert authority.read_secret(first_secret.credential_id, 1) == "first-secret"
    assert authority.read_secret(second_key.credential_id, 1) == "second-key"
    assert all("secret" not in asdict(item) and "plaintext" not in asdict(item) for item in authority.list_metadata())


def test_rotation_is_monotonic_exact_and_concurrent_stale_writer_fails(postgres_dsn: str) -> None:
    authority = _authority(postgres_dsn)
    created = authority.create(
        "INTEGRATION_SECRET",
        "b52eb762-34cf-47d4-8cca-56ef93f0d2ac",
        "api_key",
        "generation-1",
    )

    def rotate(value: str) -> object:
        try:
            return _authority(postgres_dsn).rotate(created.credential_id, 1, value)
        except OnlyCredentialError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(rotate, ("generation-2-a", "generation-2-b")))

    winners = tuple(item for item in outcomes if not isinstance(item, Exception))
    conflicts = tuple(item for item in outcomes if isinstance(item, OnlyCredentialError))
    assert len(winners) == 1
    assert winners[0].generation == 2
    assert len(conflicts) == 1 and conflicts[0].code == "CREDENTIAL_GENERATION_CONFLICT"
    third = authority.rotate(created.credential_id, 2, "generation-3")
    assert third.generation == 3
    assert authority.read_secret(created.credential_id, 3) == "generation-3"


def test_exact_generation_restart_and_ciphertext_slot_swap_fail_closed(postgres_dsn: str) -> None:
    authority = _authority(postgres_dsn)
    first = authority.create(
        "INTEGRATION_SECRET",
        "b52eb762-34cf-47d4-8cca-56ef93f0d2ac",
        "api_key",
        "first-value",
    )
    second = authority.create(
        "INTEGRATION_SECRET",
        "b52eb762-34cf-47d4-8cca-56ef93f0d2ac",
        "api_secret",
        "second-value",
    )
    rotated = authority.rotate(first.credential_id, 1, "rotated-value")

    restarted = _authority(postgres_dsn)
    assert restarted.read_secret(rotated.credential_id, 2) == "rotated-value"
    with pytest.raises(OnlyCredentialError) as mismatch:
        restarted.read_secret(rotated.credential_id, 1)
    assert mismatch.value.code == "CREDENTIAL_GENERATION_MISMATCH"

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE product_credential SET ciphertext = "
            "(SELECT ciphertext FROM product_credential WHERE credential_id = %s) "
            "WHERE credential_id = %s",
            (second.credential_id, first.credential_id),
        )
    with pytest.raises(OnlyCredentialError) as invalid:
        restarted.read_secret(first.credential_id, 2)
    assert invalid.value.code == "CREDENTIAL_CIPHERTEXT_INVALID"
