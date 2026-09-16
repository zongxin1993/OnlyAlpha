"""Encrypted Product credential storage; plaintext never crosses the metadata boundary."""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row

from .config import OnlyPostgresOperationalConnectionOptions

MASTER_KEY_BYTES = 32
MASTER_KEY_VERSION = 1
MASTER_KEY_FILE = Path("secrets") / "dev-master-key"


def only_ensure_dev_master_key(path: Path) -> bytes:
    """Create or read one durable development key without replacing an existing key."""

    if not path.is_absolute() or path.is_symlink():
        raise ValueError("CREDENTIAL_MASTER_KEY_PATH_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = path.read_bytes()
        if len(value) != MASTER_KEY_BYTES:
            raise ValueError("CREDENTIAL_MASTER_KEY_INVALID") from None
        return value
    value = secrets.token_bytes(MASTER_KEY_BYTES)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        value = path.read_bytes()
        if len(value) != MASTER_KEY_BYTES:
            raise ValueError("CREDENTIAL_MASTER_KEY_INVALID") from None
        return value
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    return value


@dataclass(frozen=True, slots=True)
class OnlyCredentialMetadata:
    credential_id: str
    credential_kind: str
    provider_id: str
    key_version: int
    masked_value: str
    created_at: datetime
    updated_at: datetime


class OnlyPostgresCredentialAuthority:
    """Store credentials encrypted at rest and expose metadata-only reads."""

    def __init__(
        self,
        dsn: str,
        master_key: bytes,
        *,
        options: OnlyPostgresOperationalConnectionOptions | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if len(master_key) != MASTER_KEY_BYTES:
            raise ValueError("CREDENTIAL_MASTER_KEY_INVALID")
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)
        self._key = bytes(master_key)
        self._now = now or (lambda: datetime.now(UTC))

    def put(self, credential_kind: str, provider_id: str, secret: str) -> OnlyCredentialMetadata:
        _validate_text(credential_kind, "CREDENTIAL_KIND_INVALID")
        _validate_text(provider_id, "CREDENTIAL_PROVIDER_INVALID")
        if not isinstance(secret, str) or not secret:
            raise ValueError("CREDENTIAL_SECRET_INVALID")
        credential_id = str(uuid.uuid4())
        created_at = self._now()
        if created_at.tzinfo is None or created_at.utcoffset() != UTC.utcoffset(created_at):
            raise ValueError("CREDENTIAL_TIMESTAMP_INVALID")
        ciphertext = self._encrypt(credential_kind, provider_id, secret)
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                "INSERT INTO product_credential "
                "(credential_id, credential_kind, provider_id, ciphertext, key_version, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (credential_kind, provider_id) DO UPDATE SET "
                "ciphertext = EXCLUDED.ciphertext, key_version = EXCLUDED.key_version, "
                "updated_at = EXCLUDED.updated_at "
                "RETURNING credential_id, credential_kind, provider_id, key_version, created_at, updated_at",
                (credential_id, credential_kind, provider_id, ciphertext, MASTER_KEY_VERSION, created_at, created_at),
            ).fetchone()
        if row is None:
            raise RuntimeError("CREDENTIAL_WRITE_NOT_OBSERVED")
        return _metadata(row, secret)

    def list_metadata(self) -> tuple[OnlyCredentialMetadata, ...]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT credential_id, credential_kind, provider_id, key_version, created_at, updated_at "
                "FROM product_credential ORDER BY credential_kind, provider_id"
            ).fetchall()
        return tuple(_metadata(row, None) for row in rows)

    def read_secret(self, credential_kind: str, provider_id: str) -> str:
        _validate_text(credential_kind, "CREDENTIAL_KIND_INVALID")
        _validate_text(provider_id, "CREDENTIAL_PROVIDER_INVALID")
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT ciphertext, key_version FROM product_credential "
                "WHERE credential_kind = %s AND provider_id = %s",
                (credential_kind, provider_id),
            ).fetchone()
        if row is None:
            raise LookupError("CREDENTIAL_NOT_FOUND")
        if int(row["key_version"]) != MASTER_KEY_VERSION:
            raise ValueError("CREDENTIAL_KEY_VERSION_UNSUPPORTED")
        return self._decrypt(credential_kind, provider_id, bytes(row["ciphertext"]))

    def _encrypt(self, credential_kind: str, provider_id: str, secret: str) -> bytes:
        nonce = secrets.token_bytes(12)
        aad = f"{credential_kind}\0{provider_id}".encode()
        return nonce + cast(bytes, AESGCM(self._key).encrypt(nonce, secret.encode(), aad))

    def _decrypt(self, credential_kind: str, provider_id: str, ciphertext: bytes) -> str:
        if len(ciphertext) <= 12:
            raise ValueError("CREDENTIAL_CIPHERTEXT_INVALID")
        try:
            value = AESGCM(self._key).decrypt(
                ciphertext[:12], ciphertext[12:], f"{credential_kind}\0{provider_id}".encode()
            )
            return cast(bytes, value).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise ValueError("CREDENTIAL_CIPHERTEXT_INVALID") from exc


def _metadata(row: object, secret: str | None) -> OnlyCredentialMetadata:
    values = cast(dict[str, object], row)
    return OnlyCredentialMetadata(
        credential_id=str(values["credential_id"]),
        credential_kind=str(values["credential_kind"]),
        provider_id=str(values["provider_id"]),
        key_version=int(cast(int, values["key_version"])),
        masked_value=only_mask_credential(secret),
        created_at=cast(datetime, values["created_at"]),
        updated_at=cast(datetime, values["updated_at"]),
    )


def only_mask_credential(secret: str | None) -> str:
    if not secret:
        return "****"
    return "****" if len(secret) <= 7 else f"{secret[:3]}****{secret[-4:]}"


def _validate_text(value: str, error: str) -> None:
    if not isinstance(value, str) or not value.strip() or any(character.isspace() for character in value):
        raise ValueError(error)


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "MASTER_"))]
