"""Pure installed Calculation resolution; no Research admission or business state."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
from onlyalpha_plugin_operators.registration import registrations as operators
from onlyalpha_backend_algorithms.targets.registration import registrations as targets

from onlyalpha.algorithm.type_declaration import type_declaration
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeReference,
    only_calculation_scalar_from_dict,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
    _ADAPTER_FINGERPRINTS,
    OnlyPrivateFactorAdapterV1,
    OnlyPrivateFactorIsolatedProgramHost,
    OnlyPrivateFactorSourceArtifactManifestV1,
    only_private_factor_backend_registrations,
    only_validate_private_factor_revision,
)
from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1

MAX_WORK = 8 * 1024 * 1024

# Installed resources/metadata and Arrow shared-library initialization precede
# confinement. Per-source resolution below is in memory; authored math stays
# inside the owning process's OS sandbox.
_PUBLIC_REGISTRATIONS = (*operators(), *targets())
pa.array([Decimal("1")], type=pa.decimal128(38, 18))


def _exact(value: object, fields: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ValueError("RESEARCH_CALCULATION_RESOLUTION_INVALID")
    return value


def _name(value: object) -> str:
    if type(value) is not str or not value or len(value) > 4096 or any(c.isspace() for c in value):
        raise ValueError("RESEARCH_CALCULATION_RESOLUTION_INVALID")
    return value


def private_calculation_records(registrations: Iterable[OnlyCalculationBackendRegistration]) -> list[dict[str, Any]]:
    """Actual source-owned capabilities, shared by Factor and complete graph resolution."""
    return cast(
        list[dict[str, Any]],
        json.loads(
            only_canonical_json(
                sorted(
                    [
                        {
                            "type": row.type_definition.descriptor(),
                            "backend": row.backend.value,
                            "implementation_fingerprint": row.implementation_manifest.implementation_fingerprint,
                            "state_capability": None if row.state_capability is None else row.state_capability.value,
                            "checkpoint_schema_version": row.checkpoint_schema_version,
                        }
                        for row in registrations
                        if row.implementation_manifest is not None
                    ],
                    key=only_canonical_fingerprint,
                )
            )
        ),
    )


def registry_for_sources(
    sources: list[dict[str, Any]],
    host: OnlyPrivateFactorIsolatedProgramHost | None = None,
) -> tuple[OnlyCalculationRegistry, list[dict[str, object]]]:
    """Public calculations need no artificial private Factor or authoring generation."""
    if type(sources) is not list or len(sources) > 128 or len(json.dumps(sources).encode()) > MAX_WORK:
        raise ValueError("RESEARCH_CALCULATION_RESOLUTION_BUDGET")
    registry = OnlyCalculationRegistry()
    for registration in _PUBLIC_REGISTRATIONS:
        registry.register(registration)
    artifacts: dict[str, dict[str, object]] = {}
    for raw in sources:
        source = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(raw)
        if source.factor_id in artifacts:
            raise ValueError("RESEARCH_CALCULATION_SOURCE_CONFLICT")
        validation = only_validate_private_factor_revision(source)
        manifest, code = OnlyPrivateFactorSourceArtifactManifestV1.materialize(source, validation)
        private = only_private_factor_backend_registrations(
            source,
            manifest,
            code,
            OnlyPrivateFactorAdapterV1(
                "RESEARCH", _ADAPTER_FINGERPRINTS["RESEARCH"], host or OnlyPrivateFactorIsolatedProgramHost()
            ),
            OnlyPrivateFactorAdapterV1(
                "TRADING", _ADAPTER_FINGERPRINTS["TRADING"], host or OnlyPrivateFactorIsolatedProgramHost()
            ),
        )
        for registration in private:
            registry.register(registration)
        artifacts[source.factor_id] = {
            "private_calculations": private_calculation_records(private),
            "source_artifact": manifest.to_dict(),
            "validation_evidence": {
                **validation.to_dict(),
                "validation_evidence_fingerprint": validation.validation_evidence_fingerprint,
            },
        }
    return registry, [artifacts[key] for key in sorted(artifacts)]


def trading_capabilities(payload: dict[str, Any]) -> dict[str, object]:
    """Observe actual installed TRADING metadata without creating math instances."""
    request = _exact(payload, {"schema_version", "contract", "sources", "definitions"})
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != 1
        or request["contract"] != "ONLYALPHA_TRADING_NODE_CAPABILITIES_V1"
        or type(request["definitions"]) is not list
        or not 1 <= len(request["definitions"]) <= 128
        or len(json.dumps(request).encode()) > MAX_WORK
    ):
        raise ValueError("TRADING_CAPABILITIES_INPUT_INVALID")
    registry, _ = registry_for_sources(request["sources"])
    rows: dict[str, dict[str, object]] = {}
    for raw in request["definitions"]:
        definition = OnlyCalculationDefinition.from_dict(raw)
        if definition.kind is not OnlyCalculationKind.FACTOR and not (
            definition.kind is OnlyCalculationKind.INDICATOR and definition.type_id.startswith("onlyalpha.operator.")
        ):
            raise ValueError("TRADING_CAPABILITIES_TYPE_UNAVAILABLE")
        registration = registry.resolve(
            definition.kind, definition.type_id, definition.semantic_version, OnlyCalculationBackendKind.TRADING
        )
        if (
            registration.definition_resolver is None
            or registration.implementation_manifest is None
            or registration.state_capability is None
            or registration.definition_resolver.resolve(definition.parameters, definition.input_bindings) != definition
        ):
            raise ValueError("TRADING_CAPABILITIES_IMPLEMENTATION_UNAVAILABLE")
        capability = registration.state_capability.value
        schema = registration.checkpoint_schema_version
        if (
            not (
                capability == "STATELESS"
                and schema is None
                or capability == "CHECKPOINTABLE"
                and type(schema) is int
                and schema > 0
            )
            or definition.fingerprint in rows
        ):
            raise ValueError("TRADING_CAPABILITIES_STATE_INVALID")
        rows[definition.fingerprint] = {
            "node_fingerprint": definition.fingerprint,
            "implementation_fingerprint": registration.implementation_manifest.implementation_fingerprint,
            "state_capability": capability,
            "checkpoint_schema_version": schema,
        }
    return {
        "schema_version": 1,
        "contract": request["contract"],
        "nodes": [rows[key] for key in sorted(rows)],
    }


def resolve_instances(sources: list[dict[str, Any]], instances: list[dict[str, Any]]) -> dict[str, Any]:
    """Rematerialize through actual installed type-owned resolvers, never client descriptors."""
    if type(instances) is not list or not 1 <= len(instances) <= 128 or len(json.dumps(instances).encode()) > MAX_WORK:
        raise ValueError("RESEARCH_CALCULATION_RESOLUTION_BUDGET")
    registry, artifacts = registry_for_sources(sources)
    pending: dict[str, dict[str, Any]] = {}
    for raw in instances:
        row = _exact(
            raw,
            {"instance_key", "type_reference", "parameters", "published_outputs", "input_bindings", "primary_output"},
        )
        key = _name(row["instance_key"])
        if re.fullmatch(r"[a-z][a-z0-9_]*", key) is None or key in pending:
            raise ValueError("RESEARCH_CALCULATION_INSTANCE_INVALID")
        pending[key] = row
    resolved: dict[str, tuple[OnlyCalculationDefinition, set[str]]] = {}
    nodes = []
    while pending:
        completed = []
        for key in sorted(pending):
            row = pending[key]
            reference = OnlyCalculationTypeReference.from_dict(
                _exact(row["type_reference"], {"kind", "type_id", "semantic_version"})
            )
            if reference.kind not in {
                OnlyCalculationKind.INDICATOR,
                OnlyCalculationKind.FACTOR,
                OnlyCalculationKind.TARGET,
            }:
                raise ValueError("RESEARCH_CALCULATION_TYPE_UNAVAILABLE")
            if type(row["parameters"]) is not dict or type(row["input_bindings"]) is not list:
                raise ValueError("RESEARCH_CALCULATION_INSTANCE_INVALID")
            parameters = {}
            for name, binding in row["parameters"].items():
                binding = _exact(binding, {"kind", "value"})
                if binding["kind"] != "FIXED":
                    raise ValueError("RESEARCH_CALCULATION_SWEEP_FORBIDDEN")
                parameters[_name(name)] = only_calculation_scalar_from_dict(binding["value"])
            bindings = {}
            waiting = False
            for binding in row["input_bindings"]:
                binding = _exact(binding, {"input_name", "source"})
                name = _name(binding["input_name"])
                if name in bindings:
                    raise ValueError("RESEARCH_CALCULATION_INPUT_CONFLICT")
                source = binding["source"]
                if type(source) is str:
                    bindings[name] = OnlyCalculationReference(None, "value", _name(source))
                else:
                    source = _exact(source, {"kind", "instance_key", "output_name"})
                    if source["kind"] != "VARIABLE":
                        raise ValueError("RESEARCH_CALCULATION_INPUT_INVALID")
                    parent = _name(source["instance_key"])
                    if parent not in resolved:
                        if parent not in pending:
                            raise ValueError("RESEARCH_CALCULATION_INPUT_UNAVAILABLE")
                        waiting = True
                        continue
                    definition, published = resolved[parent]
                    output = _name(source["output_name"])
                    if output not in published:
                        raise ValueError("RESEARCH_CALCULATION_OUTPUT_UNAVAILABLE")
                    bindings[name] = OnlyCalculationReference(definition.fingerprint, output, None)
            if waiting:
                continue
            registration = registry.resolve(
                reference.kind, reference.type_id, reference.semantic_version, OnlyCalculationBackendKind.RESEARCH
            )
            definition = registry.rematerialize_definition(reference, parameters, bindings)
            outputs = row["published_outputs"]
            if (
                type(outputs) is not list
                or not outputs
                or any(type(v) is not str for v in outputs)
                or len(set(outputs)) != len(outputs)
            ):
                raise ValueError("RESEARCH_CALCULATION_OUTPUT_INVALID")
            available = {output.name for output in definition.outputs}
            if (
                not set(outputs).issubset(available)
                or row["primary_output"] is not None
                and row["primary_output"] not in outputs
            ):
                raise ValueError("RESEARCH_CALCULATION_OUTPUT_UNAVAILABLE")
            implementations = []
            for backend in (OnlyCalculationBackendKind.RESEARCH, OnlyCalculationBackendKind.TRADING):
                try:
                    actual = registry.resolve(reference.kind, reference.type_id, reference.semantic_version, backend)
                except ValueError:
                    if backend is OnlyCalculationBackendKind.TRADING:
                        continue
                    raise
                if actual.definition_resolver is None or actual.implementation_manifest is None:
                    raise ValueError("RESEARCH_CALCULATION_IMPLEMENTATION_UNAVAILABLE")
                if actual.definition_resolver.resolve(parameters, bindings) != definition:
                    raise ValueError("RESEARCH_CALCULATION_BACKEND_MISMATCH")
                implementations.append(actual.implementation_manifest.to_dict())
            nodes.append(
                {
                    "instance_key": key,
                    "definition": dict(definition.to_dict()),
                    "definition_fingerprint": definition.fingerprint,
                    "type_declaration": type_declaration(registration.type_definition),
                    "implementations": implementations,
                }
            )
            resolved[key] = (definition, set(outputs))
            completed.append(key)
        if not completed:
            raise ValueError("RESEARCH_CALCULATION_GRAPH_CYCLE")
        for key in completed:
            del pending[key]
    return {
        "schema_version": 1,
        "nodes": sorted(nodes, key=lambda row: row["instance_key"]),
        "source_artifacts": artifacts,
    }
