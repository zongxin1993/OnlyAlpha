"""Deterministically project the canonical OpenAPI into external client contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import pprint
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts/research-api/v2/openapi.json"
PYTHON_PROJECTION = ROOT / "packages/client/onlyalpha-client/src/onlyalpha_client/generated/contract.py"
GENERATOR_VERSION = "1"
FORMATTER_VERSION = "ruff 0.15.22"
PRODUCT_TAG = "research-runs"
HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put", "trace"})

JsonObject = dict[str, Any]


def _load_contract() -> tuple[JsonObject, bytes]:
    raw = CONTRACT.read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError("canonical OpenAPI must be one JSON object")
    canonical = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    if raw != canonical:
        raise ValueError("canonical OpenAPI bytes are not deterministic")
    return cast(JsonObject, document), raw


def _schema_name(schema: object) -> str:
    if not isinstance(schema, dict) or not isinstance(schema.get("$ref"), str):
        raise ValueError("Product client operations require named component schemas")
    reference = cast(str, schema["$ref"])
    prefix = "#/components/schemas/"
    if not reference.startswith(prefix):
        raise ValueError(f"external OpenAPI reference is forbidden: {reference}")
    return reference.removeprefix(prefix)


def _operations(document: Mapping[str, Any]) -> dict[str, dict[str, object]]:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("canonical OpenAPI paths are missing")
    result: dict[str, dict[str, object]] = {}
    for path, path_item in sorted(paths.items()):
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method, operation in sorted(path_item.items()):
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            tags = operation.get("tags")
            if not isinstance(tags, list) or PRODUCT_TAG not in tags:
                continue
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or operation_id in result:
                raise ValueError(f"invalid or duplicate Product operationId at {method.upper()} {path}")
            request_schema: str | None = None
            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                content = request_body.get("content")
                if isinstance(content, dict) and isinstance(content.get("application/json"), dict):
                    request_schema = _schema_name(content["application/json"].get("schema"))
            responses = operation.get("responses")
            if not isinstance(responses, dict):
                raise ValueError(f"Product operation has no responses: {operation_id}")
            successes = sorted(
                (int(status), response)
                for status, response in responses.items()
                if isinstance(status, str)
                and status.isdigit()
                and 200 <= int(status) < 300
                and isinstance(response, dict)
            )
            if len(successes) != 1:
                raise ValueError(f"Product operation must have exactly one success response: {operation_id}")
            status, response = successes[0]
            content = response.get("content")
            if not isinstance(content, dict) or not isinstance(content.get("application/json"), dict):
                raise ValueError(f"Product operation success response must be JSON: {operation_id}")
            response_schema = _schema_name(content["application/json"].get("schema"))
            error_schemas = sorted(
                {
                    _schema_name(media["schema"])
                    for response_status, error_response in responses.items()
                    if isinstance(response_status, str)
                    and response_status.isdigit()
                    and not 200 <= int(response_status) < 300
                    and isinstance(error_response, dict)
                    and isinstance(error_response.get("content"), dict)
                    and isinstance(error_response["content"].get("application/json"), dict)
                    and isinstance((media := error_response["content"]["application/json"]), dict)
                    and isinstance(media.get("schema"), dict)
                }
            )
            result[operation_id] = {
                "method": method.upper(),
                "path": path,
                "request_schema": request_schema,
                "response_schema": response_schema,
                "success_status": status,
                "error_schemas": error_schemas,
            }
    if not result:
        raise ValueError(f"canonical OpenAPI has no operations tagged {PRODUCT_TAG!r}")
    return result


def _schema_closure(document: Mapping[str, Any], roots: set[str]) -> dict[str, JsonObject]:
    components = document.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(schemas, dict):
        raise ValueError("canonical OpenAPI component schemas are missing")
    selected: dict[str, JsonObject] = {}
    pending = sorted(roots)
    while pending:
        name = pending.pop(0)
        if name in selected:
            continue
        schema = schemas.get(name)
        if not isinstance(schema, dict):
            raise ValueError(f"referenced component schema is missing: {name}")
        selected[name] = cast(JsonObject, schema)
        references = _schema_references(schema)
        pending = sorted(set(pending) | (references - selected.keys()))
    return {name: selected[name] for name in sorted(selected)}


def _schema_references(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str):
            result.add(_schema_name(value))
        for child in value.values():
            result.update(_schema_references(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_schema_references(child))
    return result


def _python_type(schema: object) -> str:
    if not isinstance(schema, dict) or not schema:
        return "JSONValue"
    reference = schema.get("$ref")
    if isinstance(reference, str):
        name = _schema_name(schema)
        return "JSONValue" if name == "JsonValue" else name
    alternatives = schema.get("anyOf")
    if isinstance(alternatives, list):
        return " | ".join(dict.fromkeys(_python_type(item) for item in alternatives))
    if "const" in schema:
        return f"Literal[{schema['const']!r}]"
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return "Literal[" + ", ".join(repr(item) for item in enum) + "]"
    kind = schema.get("type")
    if kind == "null":
        return "None"
    if kind == "string":
        return "str"
    if kind == "integer":
        return "int"
    if kind == "number":
        return "int | float"
    if kind == "boolean":
        return "bool"
    if kind == "array":
        return f"list[{_python_type(schema.get('items'))}]"
    if kind == "object":
        additional = schema.get("additionalProperties")
        return f"dict[str, {_python_type(additional)}]" if isinstance(additional, dict) else "dict[str, JSONValue]"
    return "JSONValue"


def _typed_dicts(schemas: Mapping[str, JsonObject]) -> str:
    blocks: list[str] = []
    for name, schema in schemas.items():
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            if name != "JsonValue":
                blocks.append(f"type {name} = {_python_type(schema)}")
            continue
        required_raw = schema.get("required", [])
        required = set(required_raw) if isinstance(required_raw, list) else set()
        lines = [f"class {name}(TypedDict):"]
        if not properties:
            lines.append("    pass")
        for field, field_schema in sorted(properties.items()):
            annotation = _python_type(field_schema)
            if field not in required:
                annotation = f"NotRequired[{annotation}]"
            lines.append(f"    {field}: {annotation}")
        blocks.append("\n".join(lines))
    return "\n\n\n".join(blocks)


def render_python_projection() -> bytes:
    document, raw = _load_contract()
    operations = _operations(document)
    roots = {
        schema
        for operation in operations.values()
        for item in (operation["request_schema"], operation["response_schema"], *operation["error_schemas"])
        if isinstance((schema := item), str)
    }
    schemas = _schema_closure(document, roots)
    sha = hashlib.sha256(raw).hexdigest()
    source = f"""# Generated by scripts/openapi_clients.py; DO NOT EDIT.
# Generator version: {GENERATOR_VERSION}
# Formatter version: {FORMATTER_VERSION}
# Canonical OpenAPI SHA256: {sha}

from __future__ import annotations

from typing import Final, Literal, NotRequired, TypedDict

type JSONValue = bool | int | float | str | None | list[JSONValue] | dict[str, JSONValue]


{_typed_dicts(schemas)}


OPENAPI_SHA256: Final = {sha!r}
GENERATOR_VERSION: Final = {GENERATOR_VERSION!r}
OPERATIONS: Final = {pprint.pformat(operations, sort_dicts=True, width=120)}
SCHEMAS: Final = {pprint.pformat(schemas, sort_dicts=True, width=120)}
"""
    formatter = Path(sys.executable).with_name("ruff")
    version = subprocess.run([str(formatter), "--version"], check=False, capture_output=True, text=True)
    if version.returncode or version.stdout.strip() != FORMATTER_VERSION:
        raise ValueError(f"exact Python client formatter {FORMATTER_VERSION!r} is unavailable")
    formatted = subprocess.run(
        [str(formatter), "format", "--stdin-filename", str(PYTHON_PROJECTION), "-"],
        input=source,
        check=False,
        capture_output=True,
        text=True,
    )
    if formatted.returncode:
        raise ValueError(f"Python client formatter failed: {formatted.stderr.strip()}")
    return formatted.stdout.encode()


def write() -> None:
    PYTHON_PROJECTION.parent.mkdir(parents=True, exist_ok=True)
    PYTHON_PROJECTION.write_bytes(render_python_projection())


def check() -> None:
    candidate = render_python_projection()
    with tempfile.TemporaryDirectory(prefix="onlyalpha-python-client-") as raw:
        generated = Path(raw) / "contract.py"
        generated.write_bytes(candidate)
        if not PYTHON_PROJECTION.is_file() or PYTHON_PROJECTION.read_bytes() != generated.read_bytes():
            raise ValueError("generated Python client is stale; run openapi_clients.py write")
    print("OPENAPI PYTHON CLIENT CURRENT")
    print(f"GENERATOR_VERSION: {GENERATOR_VERSION}")
    print(f"FORMATTER_VERSION: {FORMATTER_VERSION}")
    print(f"OPENAPI_SHA256: {hashlib.sha256(CONTRACT.read_bytes()).hexdigest()}")
    print(f"PYTHON_PROJECTION_SHA256: {hashlib.sha256(candidate).hexdigest()}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate governed external client projections")
    parser.add_argument("command", choices=("write", "check"))
    args = parser.parse_args(argv)
    try:
        write() if args.command == "write" else check()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"OPENAPI CLIENT GENERATION FAILED: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
