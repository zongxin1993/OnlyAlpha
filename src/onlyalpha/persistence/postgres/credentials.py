"""Encrypted Product credential storage; plaintext never crosses the metadata boundary."""

from __future__ import annotations

import os
import re
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

from onlyalpha.canonical import only_canonical_json
from onlyalpha.core.clock import only_system_utc_now

from .config import OnlyPostgresOperationalConnectionOptions

MASTER_KEY_BYTES = 32
MASTER_KEY_VERSION = 1
MASTER_KEY_FILE = Path("secrets") / "dev-master-key"
_SECRET_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


class OnlyCredentialError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


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
    subject_id: str
    secret_name: str
    generation: int
    key_version: int
    created_at: datetime
    updated_at: datetime
    configured: bool = True


class OnlyPostgresCredentialAuthority:
    """Store credentials encrypted at rest and expose metadata-only reads."""

    def __init__(
        self,
        dsn: str,
        master_key: bytes,
        *,
        options: OnlyPostgresOperationalConnectionOptions | None = None,
        now: Callable[[], datetime] = only_system_utc_now,
    ) -> None:
        if len(master_key) != MASTER_KEY_BYTES:
            raise ValueError("CREDENTIAL_MASTER_KEY_INVALID")
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)
        self._key = bytes(master_key)
        self._now = now

    def create(
        self,
        credential_kind: str,
        subject_id: str,
        secret_name: str,
        secret: str,
    ) -> OnlyCredentialMetadata:
        _validate_slot(credential_kind, subject_id, secret_name)
        _validate_secret(secret)
        credential_id = str(uuid.uuid4())
        created_at = self._now()
        _validate_timestamp(created_at)
        ciphertext = self._encrypt(
            credential_id,
            credential_kind,
            subject_id,
            secret_name,
            1,
            MASTER_KEY_VERSION,
            secret,
        )
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "INSERT INTO product_credential "
                    "(credential_id, credential_kind, subject_id, secret_name, generation, ciphertext, "
                    "key_version, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s) "
                    "RETURNING credential_id::text, credential_kind, subject_id, secret_name, generation, "
                    "key_version, created_at, updated_at",
                    (
                        credential_id,
                        credential_kind,
                        subject_id,
                        secret_name,
                        ciphertext,
                        MASTER_KEY_VERSION,
                        created_at,
                        created_at,
                    ),
                ).fetchone()
        except psycopg.IntegrityError as exc:
            raise OnlyCredentialError("CREDENTIAL_GENERATION_CONFLICT", "credential slot already exists") from exc
        except psycopg.Error as exc:
            raise OnlyCredentialError("CREDENTIAL_PERSISTENCE_UNAVAILABLE") from exc
        if row is None:
            raise OnlyCredentialError("CREDENTIAL_PERSISTENCE_CONFLICT", "credential write was not observed")
        return _metadata(row)

    def rotate(self, credential_id: str, expected_generation: int, secret: str) -> OnlyCredentialMetadata:
        _validate_credential_id(credential_id)
        if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) or expected_generation < 1:
            raise OnlyCredentialError("CREDENTIAL_GENERATION_CONFLICT", "expected generation is invalid")
        _validate_secret(secret)
        updated_at = self._now()
        _validate_timestamp(updated_at)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                current = connection.execute(
                    "SELECT credential_id::text, credential_kind, subject_id, secret_name, generation, key_version "
                    "FROM product_credential WHERE credential_id = %s",
                    (credential_id,),
                ).fetchone()
                if current is None:
                    raise OnlyCredentialError("CREDENTIAL_NOT_FOUND")
                if int(cast(int, current["generation"])) != expected_generation:
                    raise OnlyCredentialError("CREDENTIAL_GENERATION_CONFLICT")
                key_version = int(cast(int, current["key_version"]))
                if key_version != MASTER_KEY_VERSION:
                    raise OnlyCredentialError("CREDENTIAL_KEY_VERSION_UNSUPPORTED")
                generation = expected_generation + 1
                ciphertext = self._encrypt(
                    credential_id,
                    str(current["credential_kind"]),
                    str(current["subject_id"]),
                    str(current["secret_name"]),
                    generation,
                    key_version,
                    secret,
                )
                row = connection.execute(
                    "UPDATE product_credential SET generation = %s, ciphertext = %s, updated_at = %s "
                    "WHERE credential_id = %s AND generation = %s "
                    "RETURNING credential_id::text, credential_kind, subject_id, secret_name, generation, "
                    "key_version, created_at, updated_at",
                    (generation, ciphertext, updated_at, credential_id, expected_generation),
                ).fetchone()
                if row is None:
                    raise OnlyCredentialError("CREDENTIAL_GENERATION_CONFLICT")
        except OnlyCredentialError:
            raise
        except psycopg.Error as exc:
            raise OnlyCredentialError("CREDENTIAL_PERSISTENCE_UNAVAILABLE") from exc
        return _metadata(row)

    def list_metadata(self) -> tuple[OnlyCredentialMetadata, ...]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(
                    "SELECT credential_id::text, credential_kind, subject_id, secret_name, generation, "
                    "key_version, created_at, updated_at FROM product_credential "
                    "ORDER BY credential_kind, subject_id, secret_name"
                ).fetchall()
        except psycopg.Error as exc:
            raise OnlyCredentialError("CREDENTIAL_PERSISTENCE_UNAVAILABLE") from exc
        return tuple(_metadata(row) for row in rows)

    def read_secret(self, credential_id: str, credential_generation: int) -> str:
        _validate_credential_id(credential_id)
        if not isinstance(credential_generation, int) or isinstance(credential_generation, bool):
            raise OnlyCredentialError("CREDENTIAL_GENERATION_MISMATCH")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT credential_id::text, credential_kind, subject_id, secret_name, generation, "
                    "ciphertext, key_version FROM product_credential WHERE credential_id = %s",
                    (credential_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyCredentialError("CREDENTIAL_PERSISTENCE_UNAVAILABLE") from exc
        if row is None:
            raise OnlyCredentialError("CREDENTIAL_NOT_FOUND")
        generation = int(cast(int, row["generation"]))
        if generation != credential_generation:
            raise OnlyCredentialError("CREDENTIAL_GENERATION_MISMATCH")
        key_version = int(cast(int, row["key_version"]))
        if key_version != MASTER_KEY_VERSION:
            raise OnlyCredentialError("CREDENTIAL_KEY_VERSION_UNSUPPORTED")
        return self._decrypt(
            str(row["credential_id"]),
            str(row["credential_kind"]),
            str(row["subject_id"]),
            str(row["secret_name"]),
            generation,
            key_version,
            bytes(row["ciphertext"]),
        )

    def _encrypt(
        self,
        credential_id: str,
        credential_kind: str,
        subject_id: str,
        secret_name: str,
        generation: int,
        key_version: int,
        secret: str,
    ) -> bytes:
        nonce = secrets.token_bytes(12)
        aad = _aad(credential_id, credential_kind, subject_id, secret_name, generation, key_version)
        return nonce + AESGCM(self._key).encrypt(nonce, secret.encode(), aad)

    def _decrypt(
        self,
        credential_id: str,
        credential_kind: str,
        subject_id: str,
        secret_name: str,
        generation: int,
        key_version: int,
        ciphertext: bytes,
    ) -> str:
        if len(ciphertext) <= 12:
            raise OnlyCredentialError("CREDENTIAL_CIPHERTEXT_INVALID")
        try:
            value = AESGCM(self._key).decrypt(
                ciphertext[:12],
                ciphertext[12:],
                _aad(credential_id, credential_kind, subject_id, secret_name, generation, key_version),
            )
            return value.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise OnlyCredentialError("CREDENTIAL_CIPHERTEXT_INVALID") from exc


def _metadata(row: object) -> OnlyCredentialMetadata:
    values = cast(dict[str, object], row)
    return OnlyCredentialMetadata(
        credential_id=str(values["credential_id"]),
        credential_kind=str(values["credential_kind"]),
        subject_id=str(values["subject_id"]),
        secret_name=str(values["secret_name"]),
        generation=int(cast(int, values["generation"])),
        key_version=int(cast(int, values["key_version"])),
        created_at=cast(datetime, values["created_at"]),
        updated_at=cast(datetime, values["updated_at"]),
    )


def _aad(
    credential_id: str,
    credential_kind: str,
    subject_id: str,
    secret_name: str,
    generation: int,
    key_version: int,
) -> bytes:
    return only_canonical_json(
        {
            "credential_id": credential_id,
            "credential_kind": credential_kind,
            "subject_id": subject_id,
            "secret_name": secret_name,
            "generation": generation,
            "key_version": key_version,
        }
    ).encode("utf-8")


def _validate_slot(credential_kind: str, subject_id: str, secret_name: str) -> None:
    for value in (credential_kind, subject_id, secret_name):
        if not isinstance(value, str) or not value.strip() or any(character.isspace() for character in value):
            raise OnlyCredentialError("CREDENTIAL_SLOT_INVALID")
    if _SECRET_NAME_PATTERN.fullmatch(secret_name) is None:
        raise OnlyCredentialError("CREDENTIAL_SLOT_INVALID")


def _validate_secret(secret: str) -> None:
    if not isinstance(secret, str) or not secret:
        raise OnlyCredentialError("CREDENTIAL_SLOT_INVALID", "secret must be non-empty")


def _validate_credential_id(credential_id: str) -> None:
    try:
        parsed = uuid.UUID(credential_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise OnlyCredentialError("CREDENTIAL_SLOT_INVALID", "credential_id is invalid") from exc
    if parsed.version != 4 or str(parsed) != credential_id:
        raise OnlyCredentialError("CREDENTIAL_SLOT_INVALID", "credential_id is invalid")


def _validate_timestamp(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise OnlyCredentialError("CREDENTIAL_SLOT_INVALID", "timestamp must be timezone-aware UTC")


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "MASTER_"))]
