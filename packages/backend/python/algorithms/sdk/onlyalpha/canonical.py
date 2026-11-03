"""Canonical serialization and fingerprints shared by composition identities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path


def only_canonical_payload(value: object) -> object:
    """Project stable values into JSON-compatible canonical data."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return only_canonical_payload(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {
            str(key): only_canonical_payload(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (set, frozenset)):
        items = (only_canonical_payload(item) for item in value)
        return sorted(items, key=only_canonical_json)
    if isinstance(value, (tuple, list)):
        return [only_canonical_payload(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: only_canonical_payload(getattr(value, item.name))
            for item in fields(value)
            if not item.name.startswith("_")
        }
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return only_canonical_payload(to_dict())
    if type(value).__str__ is not object.__str__:
        return str(value)
    raise TypeError(f"cannot canonicalize {type(value).__module__}.{type(value).__qualname__}")


def only_canonical_json(value: object) -> str:
    return json.dumps(only_canonical_payload(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def only_canonical_fingerprint(value: object) -> str:
    return hashlib.sha256(only_canonical_json(value).encode("utf-8")).hexdigest()


__all__ = ["only_canonical_fingerprint", "only_canonical_json", "only_canonical_payload"]
