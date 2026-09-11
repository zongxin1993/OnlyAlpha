"""Canonical-OpenAPI-driven Product adapter for verified Agent Tool occurrences."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast
from urllib.parse import quote, urlencode

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.agent.model import OnlyAgentToolClass
from onlyalpha.research.agent.occurrence import (
    OnlyAgentExactAuthorityReference,
    OnlyAgentExactAuthorityReferenceV2,
    OnlyAgentReferenceLocatorKind,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolRecoveryClass,
)
from onlyalpha.research.agent.occurrence_service import (
    OnlyAgentProductOperationContractV1,
    OnlyAgentProductRequestSemanticProjectionV1,
)

from ..config import OnlyProductApiEndpointConfigV1
from ..runtime import OnlyAgentExternalIoPermit, assert_external_io_permit
from .transport import OnlyHttpRequestV1, OnlyHttpTransportOutcomeV1, OnlyRawHttpTransportV1

_EXTENSION = "x-onlyalpha-agent-operation"
_EXTENSION_FIELDS = {
    "schema_version",
    "tool_class",
    "recovery_class",
    "requires_product_command_id",
    "product_command_id_transport",
    "identity_requirements",
    "owning_authority_references",
}
_OWNER_FIELDS = {"reference_kind", "reference_schema_version", "locator_kind", "response_field"}
_COMMAND_TRANSPORT_FIELDS = {"in", "name"}
_HTTP_METHODS = {"delete", "get", "patch", "post", "put"}


@dataclass(frozen=True, slots=True)
class _OwningReferenceRule:
    reference_kind: str
    reference_schema_version: int
    locator_kind: OnlyAgentReferenceLocatorKind
    response_field: str


@dataclass(frozen=True, slots=True)
class _WireOperation:
    contract: OnlyAgentProductOperationContractV1
    path_fields: tuple[str, ...]
    query_fields: tuple[str, ...]
    body_fields: tuple[str, ...]
    owner_rules: tuple[_OwningReferenceRule, ...]


class OnlyProductApiContractV2:
    """Verified view of the one canonical Product API v2 OpenAPI artifact."""

    def __init__(self, path: Path) -> None:
        raw = path.read_bytes()
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH") from exc
        if not isinstance(document, dict):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        canonical = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        if canonical != raw or document.get("info", {}).get("version") != "2":
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        self._document = cast(dict[str, Any], document)
        self._fingerprint = hashlib.sha256(raw).hexdigest()
        self._operations = self._parse_operations()
        covered = {item.contract.tool_class for item in self._operations.values()}
        if covered != set(OnlyAgentToolClass):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def load_operation_verified(
        self,
        product_api_major: int,
        product_api_contract_fingerprint: str,
        operation_identity: str,
    ) -> OnlyAgentProductOperationContractV1:
        if product_api_major != 2 or product_api_contract_fingerprint != self._fingerprint:
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        try:
            return self._operations[operation_identity].contract
        except KeyError as exc:
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH") from exc

    def validate_request_verified(
        self,
        contract: OnlyAgentProductOperationContractV1,
        value: Mapping[str, object],
    ) -> Mapping[str, object]:
        self._require_contract(contract)
        return _validated_object(value, contract.request_schema)

    def validate_response_verified(
        self,
        contract: OnlyAgentProductOperationContractV1,
        value: Mapping[str, object],
    ) -> Mapping[str, object]:
        self._require_contract(contract)
        return _validated_object(value, contract.response_schema)

    def project_request_semantics_verified(
        self,
        *,
        product_api_major: int,
        product_api_contract_fingerprint: str,
        operation_identity: str,
        canonical_validated_request: Mapping[str, object],
    ) -> OnlyAgentProductRequestSemanticProjectionV1:
        contract = self.load_operation_verified(product_api_major, product_api_contract_fingerprint, operation_identity)
        validated = self.validate_request_verified(contract, canonical_validated_request)
        return OnlyAgentProductRequestSemanticProjectionV1(operation_identity, validated)

    def verify_response_binding(
        self,
        plan: OnlyAgentToolCallPlanV1,
        canonical_response: Mapping[str, object],
        owning_authority_references: tuple[OnlyAgentExactAuthorityReference, ...],
    ) -> None:
        operation = self._operation_for_plan(plan)
        validated = self.validate_response_verified(operation.contract, canonical_response)
        expected = self.owning_references_verified(plan, validated)
        if expected != owning_authority_references:
            raise ValueError("AGENT_TOOL_RESULT_INVALID")

    def wire_request_verified(
        self,
        plan: OnlyAgentToolCallPlanV1,
        config: OnlyProductApiEndpointConfigV1,
    ) -> OnlyHttpRequestV1:
        operation = self._operation_for_plan(plan)
        request = self.validate_request_verified(operation.contract, plan.canonical_validated_request)
        path = operation.contract.http_path
        for field in operation.path_fields:
            path = path.replace("{" + field + "}", quote(str(request[field]), safe=""))
        query = urlencode([(field, str(request[field])) for field in operation.query_fields if field in request])
        if query:
            path = f"{path}?{query}"
        body_value = {field: request[field] for field in operation.body_fields if field in request}
        body = b"" if not operation.body_fields else only_canonical_json(body_value).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {config.bearer_token}",
            "Content-Type": "application/json",
        }
        if operation.contract.requires_product_command_id:
            command_id = plan.product_command_id_or_idempotency_key
            if command_id is None:
                raise ValueError("AGENT_TOOL_CALL_PLAN_INVALID")
            headers["Idempotency-Key"] = command_id
        return OnlyHttpRequestV1(
            operation.contract.http_method,
            f"{config.base_url}{path}",
            MappingProxyType(headers),
            body,
        )

    def verify_command_response_header(
        self, plan: OnlyAgentToolCallPlanV1, outcome: OnlyHttpTransportOutcomeV1
    ) -> None:
        operation = self._operation_for_plan(plan)
        if not operation.contract.requires_product_command_id or outcome.response is None:
            return
        if outcome.response.header("Idempotency-Key") != plan.product_command_id_or_idempotency_key:
            raise ValueError("AGENT_TOOL_RESULT_INVALID")

    def owning_references_verified(
        self,
        plan: OnlyAgentToolCallPlanV1,
        response: Mapping[str, object],
    ) -> tuple[OnlyAgentExactAuthorityReference, ...]:
        operation = self._operation_for_plan(plan)
        references: list[OnlyAgentExactAuthorityReference] = []
        for rule in operation.owner_rules:
            value = _field(response, rule.response_field)
            references.append(
                OnlyAgentExactAuthorityReferenceV2(
                    rule.reference_kind,
                    rule.reference_schema_version,
                    rule.locator_kind,
                    cast(str, value),
                )
            )
        return tuple(references)

    def _operation_for_plan(self, plan: OnlyAgentToolCallPlanV1) -> _WireOperation:
        contract = self.load_operation_verified(
            plan.product_api_major,
            plan.product_api_contract_fingerprint,
            plan.operation_identity,
        )
        if contract.tool_class is not plan.tool_class:
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        return self._operations[plan.operation_identity]

    def _require_contract(self, contract: OnlyAgentProductOperationContractV1) -> None:
        actual = self.load_operation_verified(
            contract.product_api_major,
            contract.product_api_contract_fingerprint,
            contract.operation_identity,
        )
        if actual != contract:
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")

    def _parse_operations(self) -> Mapping[str, _WireOperation]:
        result: dict[str, _WireOperation] = {}
        operation_ids: set[str] = set()
        paths = self._document.get("paths")
        if not isinstance(paths, dict):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        for path, path_item in paths.items():
            if not isinstance(path, str) or not isinstance(path_item, dict):
                continue
            for method, raw_operation in path_item.items():
                if method not in _HTTP_METHODS or not isinstance(raw_operation, dict):
                    continue
                operation_id = raw_operation.get("operationId")
                if not isinstance(operation_id, str) or operation_id in operation_ids:
                    raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
                operation_ids.add(operation_id)
                if _EXTENSION not in raw_operation:
                    continue
                metadata = raw_operation[_EXTENSION]
                if operation_id in result or not isinstance(metadata, dict):
                    raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
                result[operation_id] = self._parse_operation(path, method, path_item, raw_operation, metadata)
        return MappingProxyType(result)

    def _parse_operation(
        self,
        path: str,
        method: str,
        path_item: Mapping[str, Any],
        operation: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> _WireOperation:
        metadata_fields = set(metadata)
        if (
            metadata_fields
            not in (
                _EXTENSION_FIELDS,
                _EXTENSION_FIELDS - {"product_command_id_transport"},
            )
            or metadata.get("schema_version") != 1
        ):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        try:
            tool_class = OnlyAgentToolClass(metadata["tool_class"])
            recovery = OnlyAgentToolRecoveryClass(metadata["recovery_class"])
        except (KeyError, ValueError) as exc:
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH") from exc
        requires_command = metadata["requires_product_command_id"]
        transport = metadata.get("product_command_id_transport")
        if not isinstance(requires_command, bool):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        command_transport: tuple[str, str] | None = None
        if requires_command:
            if not isinstance(transport, dict) or set(transport) != _COMMAND_TRANSPORT_FIELDS:
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
            command_transport = (transport.get("in"), transport.get("name"))  # type: ignore[assignment]
            if command_transport != ("header", "Idempotency-Key"):
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        elif transport is not None:
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        identities = metadata["identity_requirements"]
        owner_values = metadata["owning_authority_references"]
        if (
            not isinstance(identities, list)
            or not all(isinstance(item, str) and item for item in identities)
            or identities != sorted(set(identities))
            or not isinstance(owner_values, list)
        ):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        request_schema, path_fields, query_fields, body_fields = self._request_schema(path_item, operation)
        properties = request_schema.get("properties", {})
        if not isinstance(properties, dict) or any(item not in properties for item in identities):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        for identity in identities:
            schema = properties[identity]
            if not isinstance(schema, dict) or not {
                "x-onlyalpha-reference-kind",
                "x-onlyalpha-reference-schema-version",
                "x-onlyalpha-reference-locator-kind",
            }.issubset(schema):
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
            _validate_reference_schema(schema)
        owner_rules: list[_OwningReferenceRule] = []
        for value in owner_values:
            if not isinstance(value, dict) or set(value) != _OWNER_FIELDS:
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
            try:
                rule = _OwningReferenceRule(
                    cast(str, value["reference_kind"]),
                    cast(int, value["reference_schema_version"]),
                    OnlyAgentReferenceLocatorKind(value["locator_kind"]),
                    cast(str, value["response_field"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH") from exc
            _validate_reference_rule(rule)
            owner_rules.append(rule)
        if recovery is OnlyAgentToolRecoveryClass.IDEMPOTENT_COMMAND and not requires_command:
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        if recovery is OnlyAgentToolRecoveryClass.MUTABLE_OBSERVATION_QUERY and operation.get(
            "x-onlyalpha-replay-safe", False
        ):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        response_schema = self._response_schema(operation)
        for rule in owner_rules:
            response_reference_schema = _field_schema(response_schema, rule.response_field)
            _validate_reference_schema(response_reference_schema)
            if (
                response_reference_schema.get("x-onlyalpha-reference-kind") != rule.reference_kind
                or response_reference_schema.get("x-onlyalpha-reference-schema-version")
                != rule.reference_schema_version
                or response_reference_schema.get("x-onlyalpha-reference-locator-kind") != rule.locator_kind.value
            ):
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        if requires_command:
            command_parameters = [
                parameter
                for parameter in (*path_item.get("parameters", []), *operation.get("parameters", []))
                if isinstance(parameter, dict)
                and parameter.get("in") == "header"
                and parameter.get("name") == "Idempotency-Key"
                and parameter.get("required") is True
            ]
            if len(command_parameters) != 1:
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
            responses = operation.get("responses")
            response = responses.get("202") if isinstance(responses, dict) else None
            if not isinstance(response, dict):
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
            response_headers = response.get("headers")
            if not isinstance(response_headers, dict) or "Idempotency-Key" not in response_headers:
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        contract = OnlyAgentProductOperationContractV1(
            2,
            self._fingerprint,
            cast(str, operation["operationId"]),
            tool_class,
            recovery,
            request_schema,
            response_schema,
            requires_command,
            tuple(rule.reference_kind for rule in owner_rules),
            tuple(identities),
            method.upper(),
            path,
            command_transport,
        )
        return _WireOperation(
            contract,
            tuple(path_fields),
            tuple(query_fields),
            tuple(body_fields),
            tuple(owner_rules),
        )

    def _request_schema(
        self, path_item: Mapping[str, Any], operation: Mapping[str, Any]
    ) -> tuple[Mapping[str, object], list[str], list[str], list[str]]:
        properties: dict[str, object] = {}
        required: list[str] = []
        path_fields: list[str] = []
        query_fields: list[str] = []
        for parameter in (*path_item.get("parameters", []), *operation.get("parameters", [])):
            parameter = self._resolve(cast(Mapping[str, Any], parameter))
            name = parameter.get("name")
            location = parameter.get("in")
            if location == "header" and name == "Idempotency-Key":
                continue
            if not isinstance(name, str) or location not in {"path", "query"} or name in properties:
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
            properties[name] = self._resolve(cast(Mapping[str, Any], parameter.get("schema", {})))
            (path_fields if location == "path" else query_fields).append(name)
            if parameter.get("required") is True:
                required.append(name)
        body_fields: list[str] = []
        request_body = operation.get("requestBody")
        if isinstance(request_body, dict):
            content = request_body.get("content", {})
            media = content.get("application/json", {}) if isinstance(content, dict) else {}
            body_schema = self._resolve(cast(Mapping[str, Any], media.get("schema", {})))
            body_properties = body_schema.get("properties")
            if body_schema.get("type") != "object" or not isinstance(body_properties, dict):
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
            if set(properties) & set(body_properties):
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
            properties.update(body_properties)
            body_fields.extend(body_properties)
            required.extend(cast(Sequence[str], body_schema.get("required", [])))
        return (
            {
                "type": "object",
                "properties": properties,
                "required": sorted(set(required)),
                "additionalProperties": False,
            },
            sorted(path_fields),
            sorted(query_fields),
            sorted(body_fields),
        )

    def _response_schema(self, operation: Mapping[str, Any]) -> Mapping[str, object]:
        responses = operation.get("responses")
        if not isinstance(responses, dict):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        candidates: list[Mapping[str, object]] = []
        for status, response in responses.items():
            if not isinstance(status, str) or not status.startswith("2") or not isinstance(response, dict):
                continue
            content = response.get("content", {})
            media = content.get("application/json", {}) if isinstance(content, dict) else {}
            schema = media.get("schema") if isinstance(media, dict) else None
            if isinstance(schema, dict):
                candidates.append(self._resolve(schema))
        if len(candidates) != 1:
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        return candidates[0]

    def _resolve(
        self,
        schema: Mapping[str, Any],
        resolving: frozenset[str] = frozenset(),
    ) -> Mapping[str, object]:
        if "$ref" in schema:
            if set(schema) != {"$ref"} or not isinstance(schema["$ref"], str) or not schema["$ref"].startswith("#/"):
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
            reference = schema["$ref"]
            if reference in resolving:
                return {}
            current: Any = self._document
            for part in reference[2:].split("/"):
                current = current[part.replace("~1", "/").replace("~0", "~")]
            if not isinstance(current, dict):
                raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
            return self._resolve(current, resolving | {reference})
        result: dict[str, object] = {}
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                result[key] = {name: self._resolve(child, resolving) for name, child in value.items()}
            elif key == "items" and isinstance(value, dict):
                result[key] = self._resolve(value, resolving)
            elif key in {"allOf", "anyOf", "oneOf"} and isinstance(value, list):
                result[key] = [self._resolve(child, resolving) for child in value]
            else:
                result[key] = value
        return result


class OnlyContractDrivenProductApiAdapterV1:
    def __init__(
        self,
        config: OnlyProductApiEndpointConfigV1,
        transport: OnlyRawHttpTransportV1,
    ) -> None:
        self._config = config
        self._contract = OnlyProductApiContractV2(config.contract_path)
        self._transport = transport

    @property
    def contract(self) -> OnlyProductApiContractV2:
        return self._contract

    def invoke(
        self,
        plan: OnlyAgentToolCallPlanV1,
        permit: OnlyAgentExternalIoPermit,
    ) -> OnlyHttpTransportOutcomeV1:
        assert_external_io_permit(permit, agent_session_fingerprint=plan.agent_session_fingerprint)
        request = self._contract.wire_request_verified(plan, self._config)
        return self._transport.send(request, permit)


def _validate_reference_schema(schema: Mapping[str, object]) -> None:
    try:
        rule = _OwningReferenceRule(
            cast(str, schema["x-onlyalpha-reference-kind"]),
            cast(int, schema["x-onlyalpha-reference-schema-version"]),
            OnlyAgentReferenceLocatorKind(cast(str, schema["x-onlyalpha-reference-locator-kind"])),
            "field",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH") from exc
    _validate_reference_rule(rule)


def _validate_reference_rule(rule: _OwningReferenceRule) -> None:
    expected = (
        OnlyAgentReferenceLocatorKind.UUID4
        if rule.reference_kind == "RESEARCH_RUN"
        else OnlyAgentReferenceLocatorKind.SHA256
    )
    if (
        not rule.reference_kind
        or isinstance(rule.reference_schema_version, bool)
        or rule.reference_schema_version <= 0
        or rule.locator_kind is not expected
        or not rule.response_field
    ):
        raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")


def _field(value: Mapping[str, object], path: str) -> object:
    current: object = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise ValueError("AGENT_TOOL_RESULT_INVALID")
        current = current[part]
    if not isinstance(current, str):
        raise ValueError("AGENT_TOOL_RESULT_INVALID")
    return current


def _field_schema(schema: Mapping[str, object], path: str) -> Mapping[str, object]:
    current = schema
    for part in path.split("."):
        properties = current.get("properties")
        if not isinstance(properties, Mapping) or part not in properties or not isinstance(properties[part], Mapping):
            raise ValueError("AGENT_PRODUCT_API_CONTRACT_MISMATCH")
        current = cast(Mapping[str, object], properties[part])
    return current


def _validated_object(value: Mapping[str, object], schema: Mapping[str, object]) -> Mapping[str, object]:
    _validate_json_schema(value, schema)
    decoded = json.loads(only_canonical_json(value))
    if not isinstance(decoded, dict):  # pragma: no cover - root checked above
        raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
    return MappingProxyType(decoded)


def _validate_json_schema(value: object, schema: Mapping[str, object]) -> None:
    if "allOf" in schema:
        for child in cast(Sequence[Mapping[str, object]], schema["allOf"]):
            _validate_json_schema(value, child)
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            matches = 0
            for child in cast(Sequence[Mapping[str, object]], schema[keyword]):
                try:
                    _validate_json_schema(value, child)
                    matches += 1
                except ValueError:
                    pass
            if matches == 0 or (keyword == "oneOf" and matches != 1):
                raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
            return
    if "const" in schema and value != schema["const"]:
        raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
    if "enum" in schema and value not in cast(Sequence[object], schema["enum"]):
        raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
    expected = schema.get("type")
    types = {expected} if isinstance(expected, str) else set(cast(Sequence[str], expected or ()))
    matches = (
        "object" in types
        and isinstance(value, Mapping)
        or "array" in types
        and isinstance(value, (list, tuple))
        or "string" in types
        and isinstance(value, str)
        or "integer" in types
        and isinstance(value, int)
        and not isinstance(value, bool)
        or "number" in types
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        or "boolean" in types
        and isinstance(value, bool)
        or "null" in types
        and value is None
    )
    if types and not matches:
        raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
    if isinstance(value, Mapping):
        raw_properties = schema.get("properties", {})
        properties = cast(Mapping[str, object], raw_properties) if isinstance(raw_properties, Mapping) else None
        raw_required = schema.get("required", ())
        required = cast(Sequence[object], raw_required) if isinstance(raw_required, Sequence) else None
        if properties is None or required is None or not set(required).issubset(value):
            raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
        extras = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if extras and additional is False:
            raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
        for name, item in value.items():
            property_schema = properties.get(name)
            if isinstance(property_schema, Mapping):
                _validate_json_schema(item, property_schema)
            elif isinstance(additional, Mapping):
                _validate_json_schema(item, additional)
        if "minProperties" in schema and len(value) < cast(int, schema["minProperties"]):
            raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
        if "maxProperties" in schema and len(value) > cast(int, schema["maxProperties"]):
            raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
    if isinstance(value, (list, tuple)):
        raw_child = schema.get("items")
        if isinstance(raw_child, Mapping):
            for item in value:
                _validate_json_schema(item, raw_child)
        if "minItems" in schema and len(value) < cast(int, schema["minItems"]):
            raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
        if "maxItems" in schema and len(value) > cast(int, schema["maxItems"]):
            raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
    if isinstance(value, str):
        if "pattern" in schema and re.fullmatch(cast(str, schema["pattern"]), value) is None:
            raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
        if "minLength" in schema and len(value) < cast(int, schema["minLength"]):
            raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")
        if "maxLength" in schema and len(value) > cast(int, schema["maxLength"]):
            raise ValueError("AGENT_PRODUCT_SCHEMA_VALIDATION_FAILED")


__all__ = ["OnlyContractDrivenProductApiAdapterV1", "OnlyProductApiContractV2"]
