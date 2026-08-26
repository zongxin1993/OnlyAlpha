from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from onlyalpha_api import create_research_app
from onlyalpha_api.health import OnlyKernelResearchReadinessProjection

from onlyalpha.application.product_boundary import only_compose_research_product_boundary
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.kernel import OnlyAlphaKernelHost
from onlyalpha.research.artifact.model import OnlyResearchArtifact
from onlyalpha.research.command import OnlyResearchCommandService, OnlyResearchRunQueryService
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.operations.readiness import OnlyResearchReadiness, OnlyResearchReadinessStatus

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_RELATIVE = Path("contracts/research-api/v2/openapi.json")
CONTRACT = ROOT / CONTRACT_RELATIVE
WEB = ROOT / "apps/onlyalpha-web"
GENERATED_CLIENT = WEB / "src/api/research/generated.ts"
OPENAPI_TYPESCRIPT = WEB / "node_modules/.bin/openapi-typescript"
API_MAJOR = 2
HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put", "trace"})
GIT_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SUPPORTED_COMPATIBILITY_KEYWORDS = frozenset(
    {
        "$ref",
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "discriminator",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "items",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "not",
        "oneOf",
        "pattern",
        "properties",
        "required",
        "type",
    }
)
NON_SEMANTIC_SCHEMA_KEYWORDS = frozenset({"default", "deprecated", "description", "example", "examples", "title"})

JsonObject = dict[str, Any]


class ContractChange(StrEnum):
    UNCHANGED = "UNCHANGED"
    COMPATIBLE = "COMPATIBLE"
    BREAKING = "BREAKING"


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    change: ContractChange
    breaking_changes: tuple[str, ...]


class _AdditionalPropertiesKind(StrEnum):
    ALLOW_ANY = "ALLOW_ANY"
    FORBID = "FORBID"
    SCHEMA = "SCHEMA"


@dataclass(slots=True)
class _ComparisonState:
    visited: set[tuple[str, str, str]]


class _ContractReader:
    def load_verified(self, research_result_fingerprint: str) -> OnlyResearchArtifact:
        raise RuntimeError(f"OpenAPI generation must not load Artifact {research_result_fingerprint}")


class _ContractDatasetResolver:
    def resolve_verified(self, definition: object) -> object:
        raise RuntimeError(f"OpenAPI generation must not resolve Dataset {definition}")


def canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def parse_document(raw: bytes, *, source: str) -> JsonObject:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{source} must contain one JSON object")
    return cast(JsonObject, value)


def contract_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def render_document() -> JsonObject:
    calculations = OnlyCalculationRegistry()
    kernel = OnlyAlphaKernelHost()
    kernel.start()
    try:
        app = create_research_app(
            _ContractReader(),
            only_compose_research_product_boundary(
                admission=kernel,
                commands=cast(OnlyResearchCommandService, object()),
                queries=cast(OnlyResearchRunQueryService, object()),
            ),
            calculations,
            OnlyResearchDefinitionResolver(calculations, _ContractDatasetResolver()),  # type: ignore[arg-type]
            OnlyKernelResearchReadinessProjection(
                kernel,
                OnlyResearchReadiness(OnlyResearchReadinessStatus.READY, ()),
            ),
        )
        return app.openapi()
    finally:
        kernel.stop()


def rendered_contract() -> bytes:
    return canonical_bytes(render_document())


def _resolve_pointer(document: Mapping[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise ValueError(f"external OpenAPI reference is forbidden: {reference}")
    value: Any = document
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"unresolved OpenAPI reference: {reference}")
        value = value[part]
    return value


def _schema_roots(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    roots: list[Mapping[str, Any]] = []
    components = document.get("components")
    if isinstance(components, dict):
        schemas = components.get("schemas")
        if isinstance(schemas, dict):
            roots.extend(value for _, value in sorted(schemas.items()) if isinstance(value, dict))

    paths = document.get("paths")
    if not isinstance(paths, dict):
        return roots
    for _, path_item in sorted(paths.items()):
        if not isinstance(path_item, dict):
            continue
        path_parameters = path_item.get("parameters", [])
        if isinstance(path_parameters, list):
            roots.extend(
                parameter["schema"]
                for parameter in path_parameters
                if isinstance(parameter, dict) and isinstance(parameter.get("schema"), dict)
            )
        for method, operation in sorted(path_item.items()):
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            parameters = operation.get("parameters", [])
            if isinstance(parameters, list):
                roots.extend(
                    parameter["schema"]
                    for parameter in parameters
                    if isinstance(parameter, dict) and isinstance(parameter.get("schema"), dict)
                )
            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                content = request_body.get("content")
                if isinstance(content, dict):
                    roots.extend(
                        media["schema"]
                        for _, media in sorted(content.items())
                        if isinstance(media, dict) and isinstance(media.get("schema"), dict)
                    )
            responses = operation.get("responses")
            if isinstance(responses, dict):
                for _, response in sorted(responses.items()):
                    if not isinstance(response, dict):
                        continue
                    content = response.get("content")
                    if isinstance(content, dict):
                        roots.extend(
                            media["schema"]
                            for _, media in sorted(content.items())
                            if isinstance(media, dict) and isinstance(media.get("schema"), dict)
                        )
    return roots


def schema_vocabulary(document: Mapping[str, Any]) -> frozenset[str]:
    vocabulary: set[str] = set()

    def visit(schema: Any) -> None:
        if not isinstance(schema, dict):
            return
        vocabulary.update(schema)
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for _, child in sorted(properties.items()):
                visit(child)
        visit(schema.get("items"))
        additional_properties = schema.get("additionalProperties")
        if isinstance(additional_properties, dict):
            visit(additional_properties)
        for keyword in ("allOf", "anyOf", "oneOf"):
            children = schema.get(keyword)
            if isinstance(children, list):
                for child in children:
                    visit(child)
        visit(schema.get("not"))

    for root in _schema_roots(document):
        visit(root)
    return frozenset(vocabulary)


def validate_schema_vocabulary(document: Mapping[str, Any]) -> None:
    unsupported = schema_vocabulary(document) - SUPPORTED_COMPATIBILITY_KEYWORDS - NON_SEMANTIC_SCHEMA_KEYWORDS
    if unsupported:
        keyword = sorted(unsupported)[0]
        raise ValueError(f"unsupported schema compatibility keyword {keyword}")


def lint_contract(document: Mapping[str, Any]) -> None:
    errors: list[str] = []
    openapi = document.get("openapi")
    info = document.get("info")
    paths = document.get("paths")
    if not isinstance(openapi, str) or not openapi.startswith("3."):
        errors.append("openapi must declare a 3.x version")
    if not isinstance(info, dict) or not isinstance(info.get("title"), str):
        errors.append("info.title must be a string")
    elif info.get("version") != str(API_MAJOR):
        errors.append(f"info.version must identify API major {API_MAJOR}")
    if not isinstance(paths, dict):
        errors.append("paths must be an object")
        paths = {}

    operation_ids: dict[str, str] = {}
    for path, path_item in sorted(paths.items()):
        if not isinstance(path, str) or not (path.startswith(f"/api/v{API_MAJOR}/") or path.startswith("/health/")):
            errors.append(f"path is outside the v{API_MAJOR} or health namespace: {path}")
        if not isinstance(path_item, dict):
            errors.append(f"path item must be an object: {path}")
            continue
        for method, operation in sorted(path_item.items()):
            if method not in HTTP_METHODS:
                continue
            location = f"{method.upper()} {path}"
            if not isinstance(operation, dict):
                errors.append(f"operation must be an object: {location}")
                continue
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                errors.append(f"operationId is required: {location}")
            elif operation_id in operation_ids:
                errors.append(f"duplicate operationId {operation_id}: {operation_ids[operation_id]} and {location}")
            else:
                operation_ids[operation_id] = location
            if not isinstance(operation.get("responses"), dict) or not operation["responses"]:
                errors.append(f"responses are required: {location}")

    def inspect(value: Any) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference is not None:
                if not isinstance(reference, str):
                    errors.append("$ref must be a string")
                else:
                    try:
                        _resolve_pointer(document, reference)
                    except ValueError as exc:
                        errors.append(str(exc))
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(document)
    try:
        validate_schema_vocabulary(document)
    except ValueError as exc:
        errors.append(str(exc))
    if errors:
        raise ValueError("OpenAPI lint failed:\n" + "\n".join(f"- {item}" for item in sorted(set(errors))))


def _resolved_schema(schema: Any, document: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(schema, dict):
        return {}
    reference = schema.get("$ref")
    if isinstance(reference, str):
        resolved = _resolve_pointer(document, reference)
        if not isinstance(resolved, dict):
            raise ValueError(f"schema reference does not resolve to an object: {reference}")
        if len(schema) == 1:
            return resolved
        combined = dict(resolved)
        combined.update((key, value) for key, value in schema.items() if key != "$ref")
        return combined
    return schema


def _types(schema: Mapping[str, Any]) -> frozenset[str]:
    value = schema.get("type")
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    return frozenset()


def _schema_identity(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "empty"
    reference = schema.get("$ref")
    if isinstance(reference, str):
        siblings = {key: value for key, value in schema.items() if key != "$ref"}
        suffix = hashlib.sha256(canonical_bytes(siblings)).hexdigest() if siblings else ""
        return f"ref:{reference}:{suffix}"
    return f"schema:{hashlib.sha256(canonical_bytes(schema)).hexdigest()}"


def _allowed_values(schema: Mapping[str, Any]) -> frozenset[str] | None:
    values: set[str] | None = None
    enum = schema.get("enum")
    if isinstance(enum, list):
        values = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in enum}
    if "const" in schema:
        const = {json.dumps(schema["const"], sort_keys=True, ensure_ascii=False)}
        values = const if values is None else values & const
    return None if values is None else frozenset(values)


def _additional_properties(schema: Mapping[str, Any]) -> tuple[_AdditionalPropertiesKind, Any]:
    value = schema.get("additionalProperties", True)
    if value is True:
        return _AdditionalPropertiesKind.ALLOW_ANY, None
    if value is False:
        return _AdditionalPropertiesKind.FORBID, None
    if isinstance(value, dict):
        return _AdditionalPropertiesKind.SCHEMA, value
    raise ValueError("additionalProperties must be a boolean or schema object")


def _constraint_change(
    old: Mapping[str, Any], new: Mapping[str, Any], *, direction: str, keyword: str, lower: bool
) -> bool:
    old_present = keyword in old
    new_present = keyword in new
    if direction == "request":
        if not new_present:
            return False
        if not old_present:
            return True
        return bool(new[keyword] > old[keyword] if lower else new[keyword] < old[keyword])
    if not old_present:
        return False
    if not new_present:
        return True
    return bool(new[keyword] < old[keyword] if lower else new[keyword] > old[keyword])


def _schema_changes(
    old_schema: Any,
    new_schema: Any,
    old_document: Mapping[str, Any],
    new_document: Mapping[str, Any],
    *,
    direction: str,
    location: str,
    state: _ComparisonState | None = None,
) -> list[str]:
    if direction not in {"request", "response"}:
        raise ValueError(f"unsupported schema compatibility direction {direction}")
    if state is None:
        state = _ComparisonState(set())
    comparison = (_schema_identity(old_schema), _schema_identity(new_schema), direction)
    if comparison in state.visited:
        return []
    state.visited.add(comparison)

    old = _resolved_schema(old_schema, old_document)
    new = _resolved_schema(new_schema, new_document)
    issues: list[str] = []
    old_types = _types(old)
    new_types = _types(new)
    if old_types and new_types:
        compatible = old_types <= new_types if direction == "request" else new_types <= old_types
        if not compatible:
            issues.append(f"{location}: {direction} type changed from {sorted(old_types)} to {sorted(new_types)}")
    elif direction == "request" and not old_types and new_types:
        issues.append(f"{location}: request type was newly constrained")
    elif direction == "response" and old_types and not new_types:
        issues.append(f"{location}: response type became unconstrained")

    old_values = _allowed_values(old)
    new_values = _allowed_values(new)
    if old_values is not None and new_values is not None:
        compatible = old_values <= new_values if direction == "request" else new_values <= old_values
        if not compatible:
            issues.append(f"{location}: {direction} enum/const compatibility changed")
    elif direction == "request" and old_values is None and new_values is not None:
        issues.append(f"{location}: request enum/const was newly constrained")
    elif direction == "response" and old_values is not None and new_values is None:
        issues.append(f"{location}: response enum/const became unconstrained")

    old_required = {item for item in old.get("required", []) if isinstance(item, str)}
    new_required = {item for item in new.get("required", []) if isinstance(item, str)}
    required_breaks = new_required - old_required if direction == "request" else old_required - new_required
    for name in sorted(required_breaks):
        issues.append(f"{location}.{name}: {direction} requiredness changed incompatibly")

    old_properties_value = old.get("properties")
    new_properties_value = new.get("properties")
    old_properties: Mapping[str, Any] = old_properties_value if isinstance(old_properties_value, dict) else {}
    new_properties: Mapping[str, Any] = new_properties_value if isinstance(new_properties_value, dict) else {}
    for name, old_property in sorted(old_properties.items()):
        if name not in new_properties:
            issues.append(f"{location}.{name}: {direction} property was removed")
            continue
        issues.extend(
            _schema_changes(
                old_property,
                new_properties[name],
                old_document,
                new_document,
                direction=direction,
                location=f"{location}.{name}",
                state=state,
            )
        )

    old_additional_kind, old_additional_schema = _additional_properties(old)
    new_additional_kind, new_additional_schema = _additional_properties(new)
    if direction == "response":
        for name in sorted(new_properties.keys() - old_properties.keys()):
            if old_additional_kind is _AdditionalPropertiesKind.FORBID:
                issues.append(
                    f"{location}.{name}: response property was added but old schema forbids additional properties"
                )
            elif old_additional_kind is _AdditionalPropertiesKind.SCHEMA:
                issues.extend(
                    _schema_changes(
                        old_additional_schema,
                        new_properties[name],
                        old_document,
                        new_document,
                        direction="response",
                        location=f"{location}.{name}",
                        state=state,
                    )
                )

    if "items" in old and "items" in new:
        issues.extend(
            _schema_changes(
                old["items"],
                new["items"],
                old_document,
                new_document,
                direction=direction,
                location=f"{location}[]",
                state=state,
            )
        )
    elif direction == "request" and "items" not in old and "items" in new:
        issues.append(f"{location}[]: request items were newly constrained")
    elif direction == "response" and "items" in old and "items" not in new:
        issues.append(f"{location}[]: response items became unconstrained")

    if (
        old_additional_kind is _AdditionalPropertiesKind.SCHEMA
        and new_additional_kind is _AdditionalPropertiesKind.SCHEMA
    ):
        issues.extend(
            _schema_changes(
                old_additional_schema,
                new_additional_schema,
                old_document,
                new_document,
                direction=direction,
                location=f"{location}.*",
                state=state,
            )
        )
    elif direction == "request":
        compatible_additional = (
            old_additional_kind is _AdditionalPropertiesKind.FORBID
            or new_additional_kind is _AdditionalPropertiesKind.ALLOW_ANY
        )
        if not compatible_additional:
            issues.append(f"{location}.*: request additionalProperties narrowed")
    else:
        compatible_additional = (
            old_additional_kind is _AdditionalPropertiesKind.ALLOW_ANY
            or new_additional_kind is _AdditionalPropertiesKind.FORBID
        )
        if not compatible_additional:
            issues.append(f"{location}.*: response additionalProperties broadened")

    for keyword in ("anyOf", "oneOf", "allOf"):
        if old.get(keyword) != new.get(keyword):
            issues.append(f"{location}: {direction} schema composition {keyword} changed")
            continue
        old_composition = old.get(keyword)
        new_composition = new.get(keyword)
        if isinstance(old_composition, list) and isinstance(new_composition, list):
            for index, (old_branch, new_branch) in enumerate(zip(old_composition, new_composition, strict=True)):
                issues.extend(
                    _schema_changes(
                        old_branch,
                        new_branch,
                        old_document,
                        new_document,
                        direction=direction,
                        location=f"{location}.{keyword}[{index}]",
                        state=state,
                    )
                )

    if old.get("not") != new.get("not"):
        issues.append(f"{location}: {direction} schema composition not changed")
    elif isinstance(old.get("not"), dict) and isinstance(new.get("not"), dict):
        inverse_direction = "response" if direction == "request" else "request"
        issues.extend(
            _schema_changes(
                old["not"],
                new["not"],
                old_document,
                new_document,
                direction=inverse_direction,
                location=f"{location}.not",
                state=state,
            )
        )

    if old.get("discriminator") != new.get("discriminator"):
        issues.append(f"{location}: {direction} discriminator changed")

    for keyword in ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"):
        try:
            changed = _constraint_change(old, new, direction=direction, keyword=keyword, lower=True)
        except TypeError as exc:
            raise ValueError(f"schema constraint {keyword} is not comparable") from exc
        if changed:
            issues.append(f"{location}: {direction} constraint {keyword} changed incompatibly")
    for keyword in ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"):
        try:
            changed = _constraint_change(old, new, direction=direction, keyword=keyword, lower=False)
        except TypeError as exc:
            raise ValueError(f"schema constraint {keyword} is not comparable") from exc
        if changed:
            issues.append(f"{location}: {direction} constraint {keyword} changed incompatibly")
    if old.get("pattern") != new.get("pattern"):
        compatible_pattern = (
            direction == "request" and "pattern" not in new or direction == "response" and "pattern" not in old
        )
        if not compatible_pattern:
            issues.append(f"{location}: {direction} pattern changed incompatibly")
    return issues


def _parameters(path_item: Mapping[str, Any], operation: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for value in (*path_item.get("parameters", []), *operation.get("parameters", [])):
        if isinstance(value, dict) and isinstance(value.get("name"), str) and isinstance(value.get("in"), str):
            result[(value["in"], value["name"])] = value
    return result


def compare_contracts(old: Mapping[str, Any], new: Mapping[str, Any]) -> CompatibilityResult:
    validate_schema_vocabulary(old)
    validate_schema_vocabulary(new)
    old_raw = canonical_bytes(old)
    new_raw = canonical_bytes(new)
    if old_raw == new_raw:
        return CompatibilityResult(ContractChange.UNCHANGED, ())
    issues: list[str] = []
    old_paths = cast(Mapping[str, Any], old.get("paths", {}))
    new_paths = cast(Mapping[str, Any], new.get("paths", {}))
    for path, old_path_value in sorted(old_paths.items()):
        if path not in new_paths:
            issues.append(f"{path}: path was removed")
            continue
        if not isinstance(old_path_value, dict) or not isinstance(new_paths[path], dict):
            issues.append(f"{path}: path item changed incompatibly")
            continue
        old_path = old_path_value
        new_path = new_paths[path]
        for method in sorted(HTTP_METHODS & old_path.keys()):
            location = f"{method.upper()} {path}"
            if method not in new_path:
                issues.append(f"{location}: operation was removed")
                continue
            old_operation = old_path[method]
            new_operation = new_path[method]
            if not isinstance(old_operation, dict) or not isinstance(new_operation, dict):
                issues.append(f"{location}: operation changed incompatibly")
                continue
            if old_operation.get("operationId") != new_operation.get("operationId"):
                issues.append(f"{location}: operationId changed")

            old_parameters = _parameters(old_path, old_operation)
            new_parameters = _parameters(new_path, new_operation)
            for key, old_parameter in sorted(old_parameters.items()):
                if key not in new_parameters:
                    issues.append(f"{location}: request parameter {key[0]}:{key[1]} was removed")
                    continue
                issues.extend(
                    _schema_changes(
                        old_parameter.get("schema", {}),
                        new_parameters[key].get("schema", {}),
                        old,
                        new,
                        direction="request",
                        location=f"{location} parameter {key[0]}:{key[1]}",
                    )
                )
                if not old_parameter.get("required", False) and new_parameters[key].get("required", False):
                    issues.append(f"{location}: request parameter {key[0]}:{key[1]} became required")
            for key, parameter in sorted(new_parameters.items()):
                if key not in old_parameters and parameter.get("required", False):
                    issues.append(f"{location}: required request parameter {key[0]}:{key[1]} was added")

            old_body = old_operation.get("requestBody")
            new_body = new_operation.get("requestBody")
            if isinstance(old_body, dict) and not isinstance(new_body, dict):
                issues.append(f"{location}: request body was removed")
            elif isinstance(new_body, dict):
                if not isinstance(old_body, dict):
                    if new_body.get("required", False):
                        issues.append(f"{location}: required request body was added")
                else:
                    if not old_body.get("required", False) and new_body.get("required", False):
                        issues.append(f"{location}: request body became required")
                    old_content = old_body.get("content", {})
                    new_content = new_body.get("content", {})
                    if isinstance(old_content, dict) and isinstance(new_content, dict):
                        for media_type, old_media in sorted(old_content.items()):
                            if media_type not in new_content:
                                issues.append(f"{location}: request content type {media_type} was removed")
                            elif isinstance(old_media, dict) and isinstance(new_content[media_type], dict):
                                issues.extend(
                                    _schema_changes(
                                        old_media.get("schema", {}),
                                        new_content[media_type].get("schema", {}),
                                        old,
                                        new,
                                        direction="request",
                                        location=f"{location} request {media_type}",
                                    )
                                )

            old_responses = old_operation.get("responses", {})
            new_responses = new_operation.get("responses", {})
            if isinstance(old_responses, dict) and isinstance(new_responses, dict):
                for status in sorted(new_responses.keys() - old_responses.keys()):
                    issues.append(f"{location}: response status {status} was added")
                for status, old_response in sorted(old_responses.items()):
                    if status not in new_responses:
                        issues.append(f"{location}: response status {status} was removed")
                        continue
                    new_response = new_responses[status]
                    if not isinstance(old_response, dict) or not isinstance(new_response, dict):
                        continue
                    old_content = old_response.get("content", {})
                    new_content = new_response.get("content", {})
                    if isinstance(old_content, dict) and isinstance(new_content, dict):
                        for media_type in sorted(new_content.keys() - old_content.keys()):
                            issues.append(f"{location}: response {status} content type {media_type} was added")
                        for media_type, old_media in sorted(old_content.items()):
                            if media_type not in new_content:
                                issues.append(f"{location}: response {status} content type {media_type} was removed")
                            elif isinstance(old_media, dict) and isinstance(new_content[media_type], dict):
                                issues.extend(
                                    _schema_changes(
                                        old_media.get("schema", {}),
                                        new_content[media_type].get("schema", {}),
                                        old,
                                        new,
                                        direction="response",
                                        location=f"{location} response {status} {media_type}",
                                    )
                                )

    unique = tuple(sorted(set(issues)))
    return CompatibilityResult(ContractChange.BREAKING if unique else ContractChange.COMPATIBLE, unique)


def load_git_baseline(base_sha: str) -> tuple[str, JsonObject, bytes]:
    if GIT_SHA.fullmatch(base_sha) is None:
        raise ValueError("BASE_SHA must be a full lowercase Git object ID")
    verified = subprocess.run(
        ["git", "rev-parse", "--verify", f"{base_sha}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if verified.returncode or verified.stdout.strip() != base_sha:
        raise ValueError(f"BASE_SHA is not an exact available commit: {base_sha}")
    shown = subprocess.run(
        ["git", "show", f"{base_sha}:{CONTRACT_RELATIVE.as_posix()}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if shown.returncode:
        raise ValueError(f"canonical v{API_MAJOR} contract is missing from BASE_SHA {base_sha}")
    document = parse_document(shown.stdout, source=f"{base_sha}:{CONTRACT_RELATIVE}")
    baseline = canonical_bytes(document)
    if shown.stdout != baseline:
        raise ValueError(f"historical contract in BASE_SHA {base_sha} is not canonical")
    lint_contract(document)
    return base_sha, document, baseline


def check_current_contract() -> tuple[JsonObject, bytes]:
    rendered = rendered_contract()
    if not CONTRACT.is_file() or CONTRACT.read_bytes() != rendered:
        raise ValueError("Research API OpenAPI contract is stale; run openapi_contract.py write")
    document = parse_document(rendered, source=str(CONTRACT_RELATIVE))
    lint_contract(document)
    return document, rendered


def check_generated_client() -> None:
    if not OPENAPI_TYPESCRIPT.is_file():
        raise ValueError("pinned openapi-typescript is unavailable; run npm ci in apps/onlyalpha-web")
    with tempfile.TemporaryDirectory(prefix="onlyalpha-openapi-") as raw:
        candidate = Path(raw) / "generated.ts"
        completed = subprocess.run(
            [str(OPENAPI_TYPESCRIPT), str(CONTRACT), "-o", str(candidate)],
            cwd=WEB,
            env=os.environ.copy(),
            check=False,
        )
        if completed.returncode:
            raise ValueError("pinned openapi-typescript generation failed")
        if not GENERATED_CLIENT.is_file() or candidate.read_bytes() != GENERATED_CLIENT.read_bytes():
            raise ValueError("generated Research API TypeScript contract is stale; run npm run api:generate")


def _print_check(raw: bytes) -> None:
    print("OPENAPI CONTRACT CURRENT")
    print(f"API_MAJOR: {API_MAJOR}")
    print(f"HEAD_CONTRACT_SHA256: {contract_sha256(raw)}")
    print("STRUCTURAL_LINT: PASS")
    print("ONLYALPHA_POLICY_LINT: PASS")


def _verify(base_sha: str) -> None:
    candidate_document, candidate = check_current_contract()
    exact_base, baseline_document, baseline = load_git_baseline(base_sha)
    result = compare_contracts(baseline_document, candidate_document)
    check_generated_client()
    print("OPENAPI CONTRACT VERIFIED")
    print(f"API_MAJOR: {API_MAJOR}")
    print(f"BASE_GIT_SHA: {exact_base}")
    print(f"BASE_CONTRACT_SHA256: {contract_sha256(baseline)}")
    print(f"HEAD_CONTRACT_SHA256: {contract_sha256(candidate)}")
    print(f"CONTRACT_CHANGE: {result.change.value}")
    print(f"BREAKING_CHANGES: {len(result.breaking_changes)}")
    print("STRUCTURAL_LINT: PASS")
    print("ONLYALPHA_POLICY_LINT: PASS")
    print("GENERATED_TYPESCRIPT_FRESHNESS: PASS")
    for issue in result.breaking_changes:
        print(f"BREAKING: {issue}")
    if result.change is ContractChange.BREAKING:
        raise ValueError("v2 breaking changes are forbidden")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Govern the canonical OnlyAlpha Research API v2 contract")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("write")
    subparsers.add_parser("check")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--base", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "write":
            CONTRACT.parent.mkdir(parents=True, exist_ok=True)
            CONTRACT.write_bytes(rendered_contract())
        elif args.command == "check":
            _, raw = check_current_contract()
            _print_check(raw)
        else:
            _verify(cast(str, args.base))
    except ValueError as exc:
        parser.exit(1, f"OPENAPI CONTRACT FAILED: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
