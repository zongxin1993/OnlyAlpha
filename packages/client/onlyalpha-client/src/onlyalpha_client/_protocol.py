"""Runtime admission of generated OpenAPI response projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from .errors import OnlyAlphaProtocolError
from .generated.contract import SCHEMAS


def _resolve(reference: str) -> Mapping[str, Any]:
    prefix = "#/components/schemas/"
    if not reference.startswith(prefix):
        raise OnlyAlphaProtocolError(f"unsupported OpenAPI reference: {reference}")
    name = reference.removeprefix(prefix)
    schema = SCHEMAS.get(name)
    if not isinstance(schema, Mapping):
        raise OnlyAlphaProtocolError(f"generated OpenAPI schema is missing: {name}")
    return cast(Mapping[str, Any], schema)


def _admit(schema: Mapping[str, Any], value: Any, path: str) -> None:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        _admit(_resolve(reference), value, path)
        return
    alternatives = schema.get("anyOf")
    if isinstance(alternatives, list):
        for alternative in alternatives:
            if not isinstance(alternative, dict):
                continue
            try:
                _admit(alternative, value, path)
            except OnlyAlphaProtocolError:
                continue
            return
        raise OnlyAlphaProtocolError(f"{path} does not match any governed schema alternative")
    if "const" in schema and value != schema["const"]:
        raise OnlyAlphaProtocolError(f"{path} must equal {schema['const']!r}")
    expected = schema.get("type")
    if expected == "null":
        if value is not None:
            raise OnlyAlphaProtocolError(f"{path} must be null")
        return
    if expected == "string":
        if not isinstance(value, str):
            raise OnlyAlphaProtocolError(f"{path} must be a string")
        return
    if expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise OnlyAlphaProtocolError(f"{path} must be an integer")
        return
    if expected == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise OnlyAlphaProtocolError(f"{path} must be a number")
        return
    if expected == "boolean":
        if not isinstance(value, bool):
            raise OnlyAlphaProtocolError(f"{path} must be a boolean")
        return
    if expected == "array":
        if isinstance(value, str | bytes) or not isinstance(value, Sequence):
            raise OnlyAlphaProtocolError(f"{path} must be an array")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                _admit(items, item, f"{path}[{index}]")
        return
    if expected == "object" or "properties" in schema or "additionalProperties" in schema:
        if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
            raise OnlyAlphaProtocolError(f"{path} must be an object")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise OnlyAlphaProtocolError(f"generated schema for {path} has invalid properties")
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise OnlyAlphaProtocolError(f"generated schema for {path} has invalid required fields")
        missing = sorted(set(required).difference(value))
        if missing:
            raise OnlyAlphaProtocolError(f"{path} is missing required fields: {', '.join(missing)}")
        additional = schema.get("additionalProperties", True)
        unknown = sorted(set(value).difference(properties))
        if additional is False and unknown:
            raise OnlyAlphaProtocolError(f"{path} contains unknown fields: {', '.join(unknown)}")
        for name, child in properties.items():
            if name in value and isinstance(child, dict):
                _admit(child, value[name], f"{path}.{name}")
        if isinstance(additional, dict):
            for name in unknown:
                _admit(additional, value[name], f"{path}.{name}")


def admit_schema(name: str, value: Any) -> None:
    schema = SCHEMAS.get(name)
    if not isinstance(schema, Mapping):
        raise OnlyAlphaProtocolError(f"generated OpenAPI schema is missing: {name}")
    _admit(cast(Mapping[str, Any], schema), value, "$")


__all__ = ["admit_schema"]
