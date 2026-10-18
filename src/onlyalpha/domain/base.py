"""Serialization contract for immutable domain models."""

import json
import re
import types
from collections.abc import Mapping
from dataclasses import fields
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Self, get_args, get_origin, get_type_hints

from onlyalpha.domain.errors import OnlyDomainError, OnlySerializationError, OnlyValidationError

_DATE_RECORD = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
_WALL_RECORD = r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?"
_UTC_RECORD = _DATE_RECORD + "T" + _WALL_RECORD + r"(?:Z|\+00:00)"


def only_require_immutable_tuple(*values: object) -> None:
    for value in values:
        if type(value) is not tuple:
            raise OnlyValidationError("domain collection requires an immutable tuple")


def _encode(value: object) -> object:
    if isinstance(value, OnlyDomainModel):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise OnlySerializationError("cannot serialize a naive datetime")
        if value.utcoffset() != timedelta(0):
            raise OnlySerializationError("absolute datetime serialization requires UTC")
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _encode(item) for key, item in value.items()}
    if value is None or isinstance(value, str | int | bool):
        return value
    raise OnlySerializationError(f"unsupported serialization value: {type(value).__name__}")


def _decode(annotation: object, value: object) -> object:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in (types.UnionType,):
        if value is None and type(None) in arguments:
            return None
        target = next(item for item in arguments if item is not type(None))
        return _decode(target, value)
    if origin in (Mapping, dict):
        if not isinstance(value, Mapping):
            raise OnlySerializationError("mapping field must be a JSON object")
        key_type, item_type = arguments
        return {_decode(key_type, key): _decode(item_type, item) for key, item in value.items()}
    if origin is tuple:
        if not isinstance(value, list):
            raise OnlySerializationError("tuple field must be encoded as a JSON array")
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(_decode(arguments[0], item) for item in value)
        if len(value) != len(arguments):
            raise OnlySerializationError("fixed tuple field has an invalid length")
        return tuple(_decode(target, item) for target, item in zip(arguments, value, strict=True))
    if annotation is Decimal:
        if not isinstance(value, str):
            raise OnlySerializationError("financial decimal must be encoded as a string")
        result = Decimal(value)
        if not result.is_finite():
            raise OnlySerializationError("financial decimal must be finite")
        return result
    if annotation is datetime:
        if not isinstance(value, str) or re.fullmatch(_UTC_RECORD, value) is None:
            raise OnlySerializationError("datetime requires explicit UTC ISO text and at most microsecond precision")
        return datetime.fromisoformat(value)
    if annotation is date:
        if not isinstance(value, str) or re.fullmatch(_DATE_RECORD, value) is None:
            raise OnlySerializationError("date requires YYYY-MM-DD text")
        return date.fromisoformat(value)
    if annotation is time:
        if not isinstance(value, str) or re.fullmatch(_WALL_RECORD, value) is None:
            raise OnlySerializationError("wall time requires HH:MM:SS text and at most microsecond precision")
        return time.fromisoformat(value)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)
    if isinstance(annotation, type) and issubclass(annotation, OnlyDomainModel):
        if not isinstance(value, Mapping):
            raise OnlySerializationError("nested domain model must be a mapping")
        return annotation.from_dict(value)
    if annotation in (str, int, bool) and type(value) is not annotation:
        raise OnlySerializationError("scalar field has an invalid type")
    return value


class OnlyDomainModel:
    """Mixin providing deterministic JSON/database-record serialization."""

    schema_version = 1

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"schema_version": self.schema_version}
        for item in fields(self):  # type: ignore[arg-type]
            payload[item.name] = _encode(getattr(self, item.name))
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        if type(payload.get("schema_version")) is not int or payload.get("schema_version") != cls.schema_version:
            raise OnlySerializationError(f"unsupported {cls.__name__} schema version")
        try:
            expected = {item.name for item in fields(cls)} | {"schema_version"}  # type: ignore[arg-type]
            if set(payload) != expected:
                raise OnlySerializationError(f"unexpected or missing {cls.__name__} fields")
            annotations = get_type_hints(cls)
            values: dict[str, object] = {}
            for item in fields(cls):  # type: ignore[arg-type]
                if item.name not in payload:
                    raise OnlySerializationError(f"missing {cls.__name__}.{item.name}")
                if not item.init:
                    if _decode(annotations[item.name], payload[item.name]) != item.default:
                        raise OnlySerializationError(f"invalid {cls.__name__}.{item.name} discriminator")
                    continue
                values[item.name] = _decode(annotations[item.name], payload[item.name])
            return cls(**values)
        except (OnlyDomainError, ArithmeticError, TypeError, ValueError) as exc:
            if isinstance(exc, OnlySerializationError):
                raise
            raise OnlySerializationError(f"invalid {cls.__name__} payload") from exc

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> Self:
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise OnlySerializationError(f"invalid {cls.__name__} JSON") from exc
        if not isinstance(decoded, dict):
            raise OnlySerializationError(f"{cls.__name__} JSON must contain an object")
        return cls.from_dict(decoded)

    def to_record(self) -> dict[str, object]:
        """Return a database-safe record containing only scalar/list structures."""
        return self.to_dict()
