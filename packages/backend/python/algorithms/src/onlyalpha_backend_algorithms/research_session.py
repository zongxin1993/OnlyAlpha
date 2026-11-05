"""Confined in-memory authored Factor/Target calls, never graph or admission authority."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

import pyarrow as pa
from onlyalpha.algorithm.type_declaration import type_declaration
from onlyalpha.calculation.decimal_execution import only_decimal_context
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind as Backend,
)
from onlyalpha.calculation.definition import (
    OnlyCalculationDataType as DataType,
)
from onlyalpha.calculation.definition import (
    OnlyCalculationDefinition,
    OnlyCalculationTypeReference,
    _reference_from_dict,
    only_calculation_scalar_from_dict,
)
from onlyalpha.calculation.definition import (
    OnlyCalculationKind as Kind,
)
from onlyalpha.canonical import only_canonical_json

from onlyalpha_backend_algorithms.research_evaluation import ManagedProgramHost
from onlyalpha_backend_algorithms.research_resolution import registry_for_sources
from onlyalpha_backend_algorithms.targets.registration import registrations as target_registrations

MAX_FRAME = 8 * 1024 * 1024
SESSION = "ONLYALPHA_AUTHORING_SESSION_V1"
RESOLVE = "ONLYALPHA_BOUND_CALCULATION_RESOLVE_V1"
EVALUATE = "ONLYALPHA_BOUND_CALCULATION_EVALUATE_V1"
INVALID = "RESEARCH_SESSION_INPUT_INVALID"


def bounded(value: object) -> None:
    if len(only_canonical_json(value).encode()) > MAX_FRAME:
        raise ValueError(INVALID)


def exact(value: object, fields: set[str], contract: str) -> dict[str, Any]:
    bounded(value)
    if (
        type(value) is not dict
        or set(value) != fields
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["contract"] != contract
    ):
        raise ValueError(INVALID)
    return value


def typed_decimal_bounds(value: object) -> None:
    """Validate normalized Decimal text before SDK fixed-f identity projection."""
    if type(value) is not dict or set(value) != {"type", "value"}:
        raise ValueError(INVALID)
    if value["type"] == "DECIMAL":
        text = value["value"]
        if type(text) is not str or len(text) > 4096 or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", text) is None:
            raise ValueError(INVALID)


class AuthoringSession:
    """Initialize once before confinement; subsequent operations use cached objects."""

    def __init__(
        self, payload: object, artifact: str, verify_core: Callable[..., Any], verify_distribution: Callable[..., Any]
    ) -> None:
        if type(payload) is not dict:
            raise ValueError(INVALID)
        request = dict(payload)
        exact(request, {"schema_version", "contract", "sources", "core_artifact", "target_artifact"}, SESSION)
        if type(request["sources"]) is not list or len(request["sources"]) > 128:
            raise ValueError(INVALID)
        core = (
            {"core_artifact_sha256": None, "core_resources_fingerprint": None}
            if request["core_artifact"] is None
            else verify_core(request["core_artifact"])
        )
        target = (
            None
            if request["target_artifact"] is None
            else verify_distribution(
                request["target_artifact"], "onlyalpha_backend_algorithms", "onlyalpha-backend-algorithms"
            )
        )
        registry, artifacts = registry_for_sources(request["sources"], ManagedProgramHost())
        if target is not None:
            for registration in target_registrations():
                registry.register(registration)
        # Initialize Arrow shared libraries before the one-way OS confinement.
        pa.array([Decimal("1")], type=pa.decimal128(38, 18))
        self.registry = registry
        self.initialization = {
            "schema_version": 1,
            "contract": SESSION,
            "algorithm_artifact": artifact,
            **core,
            "target_artifact_sha256": None if target is None else target["artifact_sha256"],
            "target_resources_fingerprint": None if target is None else target["resources_fingerprint"],
            "source_artifacts": artifacts,
        }
        bounded(self.initialization)

    def _registrations(self, definition: OnlyCalculationDefinition) -> tuple[Any, Any]:
        if (
            definition.kind not in (Kind.FACTOR, Kind.TARGET)
            or len(definition.inputs) > 128
            or len(definition.outputs) > 128
        ):
            raise ValueError(INVALID)
        reference = OnlyCalculationTypeReference(definition.kind, definition.type_id, definition.semantic_version)
        if (
            self.registry.rematerialize_definition(reference, definition.parameters, definition.input_bindings)
            != definition
        ):
            raise ValueError("RESEARCH_DEFINITION_MISMATCH")
        research = self.registry.resolve(
            definition.kind, definition.type_id, definition.semantic_version, Backend.RESEARCH
        )
        trading = (
            None
            if definition.kind is Kind.TARGET
            else self.registry.resolve(
                definition.kind, definition.type_id, definition.semantic_version, Backend.TRADING
            )
        )
        for registration in (research, trading):
            if registration is not None and (
                registration.definition_resolver is None
                or registration.implementation_manifest is None
                or registration.definition_resolver.resolve(definition.parameters, definition.input_bindings)
                != definition
            ):
                raise ValueError("RESEARCH_DEFINITION_MISMATCH")
        return research, trading

    def resolve(self, payload: object) -> dict[str, object]:
        request = exact(
            payload, {"schema_version", "contract", "type_reference", "parameters", "input_bindings"}, RESOLVE
        )
        reference = OnlyCalculationTypeReference.from_dict(request["type_reference"])
        if (
            reference.kind not in (Kind.FACTOR, Kind.TARGET)
            or type(request["parameters"]) is not dict
            or type(request["input_bindings"]) is not dict
        ):
            raise ValueError(INVALID)
        if len(request["parameters"]) > 128 or len(request["input_bindings"]) > 128:
            raise ValueError(INVALID)
        for value in request["parameters"].values():
            typed_decimal_bounds(value)
        parameters = {name: only_calculation_scalar_from_dict(value) for name, value in request["parameters"].items()}
        bindings = {name: _reference_from_dict(value) for name, value in request["input_bindings"].items()}
        definition = self.registry.rematerialize_definition(reference, parameters, bindings)
        # The type-owned resolver may supply omitted defaults. Supplied values
        # must already be normalized and cannot disappear or change identity.
        actual_parameters = dict(definition.to_dict())["parameters"]
        for name, supplied in request["parameters"].items():
            if name not in actual_parameters or only_canonical_json(actual_parameters[name]) != only_canonical_json(
                supplied
            ):
                raise ValueError(INVALID)
        research, trading = self._registrations(definition)
        capability = None
        if trading is not None:
            if trading.state_capability is None:
                raise ValueError("RESEARCH_IMPLEMENTATION_UNAVAILABLE")
            capability = {
                "implementation_fingerprint": trading.implementation_manifest.implementation_fingerprint,
                "state_capability": trading.state_capability.value,
                "checkpoint_schema_version": trading.checkpoint_schema_version,
            }
        result = {
            "definition": dict(definition.to_dict()),
            "definition_fingerprint": definition.fingerprint,
            "type_declaration": type_declaration(research.type_definition),
            "implementations": [r.implementation_manifest.to_dict() for r in (research, trading) if r is not None],
            "trading_capability": capability,
        }
        bounded(result)
        return result

    def evaluate(self, payload: object) -> dict[str, object]:
        request = exact(
            payload, {"schema_version", "contract", "definition", "input_columns", "include_trading"}, EVALUATE
        )
        if type(request["include_trading"]) is not bool:
            raise ValueError(INVALID)
        raw_definition = request["definition"]
        if type(raw_definition) is not dict:
            raise ValueError(INVALID)
        for field in ("parameters", "extensions"):
            if type(raw_definition.get(field)) is not dict:
                raise ValueError(INVALID)
            for value in raw_definition[field].values():
                typed_decimal_bounds(value)
        raw_numeric = raw_definition.get("numeric")
        if type(raw_numeric) is not dict:
            raise ValueError(INVALID)
        quantum = raw_numeric.get("output_quantum")
        if quantum is not None:
            typed_decimal_bounds({"type": "DECIMAL", "value": quantum})
        definition = OnlyCalculationDefinition.from_dict(raw_definition)
        if only_canonical_json(dict(definition.to_dict())) != only_canonical_json(request["definition"]):
            raise ValueError("RESEARCH_DEFINITION_MISMATCH")
        research, trading = self._registrations(definition)
        columns = request["input_columns"]
        if type(columns) is not dict or set(columns) != {p.name for p in definition.inputs} or not columns:
            raise ValueError(INVALID)
        if any(type(c) is not list for c in columns.values()):
            raise ValueError(INVALID)
        lengths = {len(c) for c in columns.values()}
        if len(lengths) != 1 or not 1 <= next(iter(lengths)) <= 8192:
            raise ValueError(INVALID)
        count = next(iter(lengths))
        decoded = {}
        for port in definition.inputs:
            if port.data_type is not DataType.DECIMAL:
                raise ValueError(INVALID)
            values = []
            for raw in columns[port.name]:
                if raw is None:
                    if not port.nullable:
                        raise ValueError(INVALID)
                    values.append(None)
                else:
                    if (
                        type(raw) is not str
                        or len(raw) > 40
                        or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", raw) is None
                    ):
                        raise ValueError(INVALID)
                    value = Decimal(raw)
                    if not value.is_finite():
                        raise ValueError(INVALID)
                    values.append(value)
            decoded[port.name] = values
        numeric = definition.numeric
        if numeric.rounding == "CONTEXT":
            numeric = replace(numeric, rounding=ROUND_HALF_EVEN)
        context = only_decimal_context(numeric)
        arrays = {name: pa.array(values, type=pa.decimal128(38, 18)) for name, values in decoded.items()}
        with localcontext(context):
            outputs = research.provider.execute(definition, arrays)
        values = self._outputs(definition, outputs, count, arrow=True)
        trading_values = None
        trading_fingerprint = None
        if request["include_trading"] and trading is not None:
            with localcontext(context):
                backend = trading.provider.create(definition, None)
            if getattr(backend, "definition", None) != definition or not callable(getattr(backend, "update", None)):
                raise ValueError(INVALID)
            collected = {p.name: [] for p in definition.outputs}
            for i in range(count):
                with localcontext(context):
                    row = backend.update({name: c[i] for name, c in decoded.items()})
                if not isinstance(row, Mapping):
                    raise ValueError(INVALID)
                normalized = self._outputs(definition, {name: [value] for name, value in row.items()}, 1, arrow=False)
                for name, c in normalized.items():
                    collected[name].append(c[0])
            trading_values = collected
            trading_fingerprint = trading.implementation_manifest.implementation_fingerprint
        result = {
            "values": values,
            "implementation_fingerprint": research.implementation_manifest.implementation_fingerprint,
            "trading_values": trading_values,
            "trading_implementation_fingerprint": trading_fingerprint,
        }
        bounded(result)
        return result

    @staticmethod
    def _outputs(definition: Any, outputs: object, count: int, *, arrow: bool) -> dict[str, list[str | None]]:
        if not isinstance(outputs, Mapping) or set(outputs) != {p.name for p in definition.outputs}:
            raise ValueError("RESEARCH_EVALUATION_OUTPUT_INVALID")
        result = {}
        for port in definition.outputs:
            column = outputs[port.name]
            if arrow:
                if not isinstance(column, (pa.Array, pa.ChunkedArray)) or not pa.types.is_decimal(column.type):
                    raise ValueError(INVALID)
                column = column.to_pylist()
            if type(column) is not list or len(column) != count or port.data_type is not DataType.DECIMAL:
                raise ValueError(INVALID)
            encoded = []
            for value in column:
                if value is None:
                    if not port.nullable:
                        raise ValueError(INVALID)
                    encoded.append(None)
                elif type(value) is Decimal and value.is_finite():
                    parts = value.as_tuple()
                    if len(parts.digits) + abs(int(parts.exponent)) > 4096:
                        raise ValueError(INVALID)
                    encoded.append(format(value, "f"))
                else:
                    raise ValueError(INVALID)
            result[port.name] = encoded
        return result
