"""Versioned JSON/JSONL protocol and atomic file operations."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 2
MAX_DIAGNOSTIC_CHARS = 16_384


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def bars_payload(records: tuple[dict[str, object], ...]) -> bytes:
    return ("".join(f"{canonical_json(record)}\n" for record in records)).encode("utf-8")


def bytes_fingerprint(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write_bytes(path: Path, value: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_bytes(path, (canonical_json(value) + "\n").encode("utf-8"))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("bars.jsonl records must be JSON objects")
        records.append(value)
    return tuple(records)


def tail(path: Path, maximum_chars: int = MAX_DIAGNOSTIC_CHARS) -> str | None:
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - maximum_chars * 4))
        encoded = stream.read()
        if encoded.count(b"\x00") > len(encoded) // 4:
            value = encoded.decode("utf-16-le", errors="replace")[-maximum_chars:]
        else:
            value = encoded.decode("utf-8", errors="replace")[-maximum_chars:]
    return value or None
