"""Strict canonical identity values for durable economic authority evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable


class OnlyCanonicalIdentityError(TypeError):
    """Raised when a value has no explicit formal identity representation."""


@runtime_checkable
class OnlyCanonicalIdentityProvider(Protocol):
    """Explicit owner-defined projection into the formal identity value set."""

    def canonical_identity(self) -> object: ...


def only_identity_payload(value: object) -> object:
    """Project a formal identity value to deterministic JSON data.

    This deliberately does not inspect dataclass fields, call ``to_dict()``, use
    ``str()`` for unknown objects, canonicalize paths, or assign semantics to
    unordered collections.
    """

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise OnlyCanonicalIdentityError("float is forbidden in formal economic identity")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise OnlyCanonicalIdentityError("Decimal identity values must be finite")
        return format(value, "f")
    if isinstance(value, Enum):
        return only_identity_payload(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise OnlyCanonicalIdentityError("datetime identity values must be timezone-aware UTC")
        if value.utcoffset() != timedelta(0):
            raise OnlyCanonicalIdentityError("datetime identity values must use UTC")
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [only_identity_payload(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise OnlyCanonicalIdentityError("formal identity mapping keys must be strings")
        return {key: only_identity_payload(value[key]) for key in sorted(value)}
    if isinstance(value, OnlyCanonicalIdentityProvider):
        projected = value.canonical_identity()
        if projected is value:
            raise OnlyCanonicalIdentityError("identity provider cannot return itself")
        return only_identity_payload(projected)
    raise OnlyCanonicalIdentityError(f"no formal identity for {type(value).__module__}.{type(value).__qualname__}")


def only_identity_json(value: object) -> str:
    return json.dumps(only_identity_payload(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def only_identity_fingerprint(value: object) -> str:
    return hashlib.sha256(only_identity_json(value).encode("utf-8")).hexdigest()


__all__ = [
    "OnlyCanonicalIdentityError",
    "OnlyCanonicalIdentityProvider",
    "only_identity_fingerprint",
    "only_identity_json",
    "only_identity_payload",
]
