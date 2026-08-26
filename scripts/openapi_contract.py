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

JsonObject = dict[str, Any]


class ContractChange(StrEnum):
    UNCHANGED = "UNCHANGED"
    COMPATIBLE = "COMPATIBLE"
    BREAKING = "BREAKING"


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    change: ContractChange
    breaking_changes: tuple[str, ...]


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
        return resolved
    return schema


def _types(schema: Mapping[str, Any]) -> frozenset[str]:
    value = schema.get("type")
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    return frozenset()


def _schema_changes(
    old_schema: Any,
    new_schema: Any,
    old_document: Mapping[str, Any],
    new_document: Mapping[str, Any],
    *,
    direction: str,
    location: str,
) -> list[str]:
    old = _resolved_schema(old_schema, old_document)
    new = _resolved_schema(new_schema, new_document)
    issues: list[str] = []
    old_types = _types(old)
    new_types = _types(new)
    if old_types and new_types:
        compatible = old_types <= new_types if direction == "request" else new_types <= old_types
        if not compatible:
            issues.append(f"{location}: {direction} type changed from {sorted(old_types)} to {sorted(new_types)}")

    old_enum = old.get("enum")
    new_enum = new.get("enum")
    if isinstance(old_enum, list) and isinstance(new_enum, list):
        old_values = {json.dumps(item, sort_keys=True) for item in old_enum}
        new_values = {json.dumps(item, sort_keys=True) for item in new_enum}
        compatible = old_values <= new_values if direction == "request" else new_values <= old_values
        if not compatible:
            issues.append(f"{location}: {direction} enum compatibility narrowed")
    elif direction == "request" and old_enum is None and isinstance(new_enum, list):
        issues.append(f"{location}: request enum was newly constrained")
    elif direction == "response" and isinstance(old_enum, list) and new_enum is None:
        issues.append(f"{location}: response enum became unconstrained")

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
            )
        )

    for keyword in ("anyOf", "oneOf", "allOf", "not"):
        if old.get(keyword) != new.get(keyword):
            issues.append(f"{location}: {direction} schema composition {keyword} changed")
    for keyword in ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"):
        if direction == "request" and keyword in new and (keyword not in old or new[keyword] > old[keyword]):
            issues.append(f"{location}: request constraint {keyword} narrowed")
    for keyword in ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"):
        if direction == "request" and keyword in new and (keyword not in old or new[keyword] < old[keyword]):
            issues.append(f"{location}: request constraint {keyword} narrowed")
    if direction == "request" and "pattern" in new and old.get("pattern") != new.get("pattern"):
        issues.append(f"{location}: request pattern changed")
    return issues


def _parameters(path_item: Mapping[str, Any], operation: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for value in (*path_item.get("parameters", []), *operation.get("parameters", [])):
        if isinstance(value, dict) and isinstance(value.get("name"), str) and isinstance(value.get("in"), str):
            result[(value["in"], value["name"])] = value
    return result


def compare_contracts(old: Mapping[str, Any], new: Mapping[str, Any]) -> CompatibilityResult:
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
