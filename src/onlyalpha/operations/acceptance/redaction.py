"""Fail-closed removal of secrets and user-specific absolute paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

_SENSITIVE_PARTS = ("account_id", "token", "secret", "password", "credential", "auth")


def only_redact_acceptance_value(value: object, *, key: str = "") -> object:
    lowered = key.lower()
    if any(part in lowered for part in _SENSITIVE_PARTS):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(item): only_redact_acceptance_value(content, key=str(item)) for item, content in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [only_redact_acceptance_value(item) for item in value]
    if isinstance(value, Path):
        return value.name if value.is_absolute() else value.as_posix()
    if isinstance(value, str) and _looks_absolute(value):
        return Path(value).name
    return value


def _looks_absolute(value: str) -> bool:
    return value.startswith(("/", "\\\\")) or (len(value) > 2 and value[1:3] in {":\\", ":/"})
