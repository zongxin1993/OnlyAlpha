from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import sqlite3
import time
from pathlib import Path


def sqlite_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sqlite_template(path: Path, expected_fingerprint: str | None = None) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if row is None or row[0] != "ok":
        raise ValueError(f"SQLite template integrity check failed: {path}")
    actual = sqlite_fingerprint(path)
    if expected_fingerprint is not None and actual != expected_fingerprint:
        raise ValueError(f"SQLite template fingerprint mismatch: {path}")


def copy_sqlite_template(template: Path, target: Path, expected_fingerprint: str | None = None) -> Path:
    """Copy a closed, read-only baseline into one test's private writable directory."""

    validate_sqlite_template(template, expected_fingerprint)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    shutil.copyfile(template, staging)
    staging.replace(target)
    return target


def publish_sqlite_template(source: Path, target: Path, *, timeout_seconds: float = 30.0) -> str:
    """Validate and atomically publish one immutable content-addressed cache template."""

    validate_sqlite_template(source)
    fingerprint = sqlite_fingerprint(source)
    if fingerprint not in target.name:
        raise ValueError("SQLite template filename must contain its content fingerprint")
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_suffix(target.suffix + ".lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(handle)
            break
        except FileExistsError:
            if target.exists():
                validate_sqlite_template(target, fingerprint)
                return fingerprint
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for SQLite template lock: {lock}") from None
            time.sleep(0.05)
    try:
        if not target.exists():
            staging = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            shutil.copyfile(source, staging)
            staging.replace(target)
            target.chmod(0o444)
        validate_sqlite_template(target, fingerprint)
    finally:
        lock.unlink(missing_ok=True)
    return fingerprint


def materialize_sqlite_archive(archive: Path, target: Path, expected_fingerprint: str) -> Path:
    if target.is_file():
        validate_sqlite_template(target, expected_fingerprint)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{os.getpid()}.inflate")
    try:
        with gzip.open(archive, "rb") as source, staging.open("wb") as destination:
            shutil.copyfileobj(source, destination)
        publish_sqlite_template(staging, target)
    finally:
        staging.unlink(missing_ok=True)
    validate_sqlite_template(target, expected_fingerprint)
    return target


__all__ = [
    "copy_sqlite_template",
    "materialize_sqlite_archive",
    "publish_sqlite_template",
    "sqlite_fingerprint",
    "validate_sqlite_template",
]
