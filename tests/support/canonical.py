from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path


def canonical_value(value: object) -> object:
    """Convert a domain result into a stable, JSON-compatible business value."""

    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: canonical_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): canonical_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, tuple | list | set | frozenset):
        items = [canonical_value(item) for item in value]
        return sorted(items, key=canonical_json) if isinstance(value, set | frozenset) else items
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return ((value.days * 86_400 + value.seconds) * 1_000_000_000) + value.microseconds * 1_000
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def canonical_json(value: object) -> str:
    return json.dumps(canonical_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_canonical_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(canonical_value(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
