"""Installed incremental arithmetic, called only after the managed OS sandbox.

These are algorithm states, not sealed Strategy/Runtime checkpoints or permission
proofs. The Rust owner binds them to its acknowledged history and must abandon a
session after a backend failure; this class owns no replay or recovery policy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Any, Protocol, cast

from onlyalpha.calculation.decimal_execution import only_decimal_context
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyInputDefinition,
    OnlyOutputDefinition,
)
from onlyalpha.calculation.implementation import OnlyCalculationStateCapability
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyTradingBackendFactory

from onlyalpha_backend_algorithms.research_evaluation import ManagedProgramHost, TradingBackend
from onlyalpha_backend_algorithms.research_resolution import MAX_WORK, registry_for_sources


def _json(value: object) -> bytes:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("TRADING_ALGORITHM_RECORD_INVALID") from error
    if len(encoded) > MAX_WORK:
        raise ValueError("TRADING_ALGORITHM_BUDGET_EXCEEDED")
    return encoded


def _values(values: object, ports: tuple[OnlyInputDefinition, ...] | tuple[OnlyOutputDefinition, ...]) -> None:
    if type(values) is not dict or set(values) != {port.name for port in ports}:
        raise ValueError("TRADING_ALGORITHM_PORT_MISMATCH")
    for port in ports:
        value = values[port.name]
        if value is None:
            if not port.nullable:
                raise ValueError("TRADING_ALGORITHM_NULL_INVALID")
        elif port.data_type is OnlyCalculationDataType.DECIMAL:
            if type(value) is not Decimal or not value.is_finite():
                raise ValueError("TRADING_ALGORITHM_SCALAR_INVALID")
            parts = value.as_tuple()
            if len(parts.digits) + abs(int(parts.exponent)) > 4096:
                raise ValueError("TRADING_ALGORITHM_BUDGET_EXCEEDED")
        elif port.data_type is OnlyCalculationDataType.INTEGER:
            if type(value) is not int or not -(2**63) <= value < 2**63:
                raise ValueError("TRADING_ALGORITHM_SCALAR_INVALID")
        elif port.data_type is OnlyCalculationDataType.BOOLEAN:
            if type(value) is not bool:
                raise ValueError("TRADING_ALGORITHM_SCALAR_INVALID")
        elif port.data_type is OnlyCalculationDataType.STRING:
            if type(value) is not str or len(value) > 4096:
                raise ValueError("TRADING_ALGORITHM_SCALAR_INVALID")
        else:
            raise ValueError("TRADING_ALGORITHM_SCALAR_INVALID")


class CheckpointBackend(TradingBackend, Protocol):
    def capture_checkpoint(self) -> object: ...

    def restore_checkpoint(self, payload: object) -> None: ...


class TradingGraphSession:
    """Independent named actual factories; graph order/inputs belong to the caller."""

    def __init__(self, sources: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> None:
        if type(nodes) is not dict or not 1 <= len(nodes) <= 128:
            raise ValueError("TRADING_ALGORITHM_BUDGET_EXCEEDED")
        _json(nodes)
        if any(
            type(key) is not str
            or not key
            or len(key) > 4096
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in key)
            for key in nodes
        ):
            raise ValueError("TRADING_ALGORITHM_NODE_INVALID")
        registry, _ = registry_for_sources(sources, ManagedProgramHost())
        self._entries: dict[str, tuple[OnlyCalculationDefinition, OnlyCalculationBackendRegistration]] = {}
        self._bindings: dict[str, dict[str, object]] = {}
        for key, raw in sorted(nodes.items()):
            if type(raw) is not dict:
                raise ValueError("TRADING_ALGORITHM_DEFINITION_INVALID")
            definition = OnlyCalculationDefinition.from_dict(raw)
            if not (
                definition.kind is OnlyCalculationKind.FACTOR
                or definition.kind is OnlyCalculationKind.INDICATOR
                and definition.type_id.startswith("onlyalpha.operator.")
            ):
                raise ValueError("TRADING_ALGORITHM_KIND_UNSUPPORTED")
            period = definition.parameters.get("period")
            if (
                type(period) is int
                and period > 8192
                or definition.warmup.minimum_observations > 8193
                or len(definition.inputs) > 128
                or len(definition.outputs) > 128
            ):
                raise ValueError("TRADING_ALGORITHM_BUDGET_EXCEEDED")
            registration = registry.resolve(
                definition.kind, definition.type_id, definition.semantic_version, OnlyCalculationBackendKind.TRADING
            )
            if registration.definition_resolver is None or registration.implementation_manifest is None:
                raise ValueError("TRADING_ALGORITHM_IMPLEMENTATION_UNAVAILABLE")
            if (
                _json(dict(definition.to_dict())) != _json(raw)
                or registration.definition_resolver.resolve(definition.parameters, definition.input_bindings)
                != definition
            ):
                raise ValueError("TRADING_ALGORITHM_DEFINITION_MISMATCH")
            if registration.state_capability is None or registration.state_capability not in (
                OnlyCalculationStateCapability.STATELESS,
                OnlyCalculationStateCapability.CHECKPOINTABLE,
            ):
                raise ValueError("TRADING_ALGORITHM_STATE_UNSUPPORTED")
            self._entries[key] = definition, registration
            self._bindings[key] = {
                "definition": dict(definition.to_dict()),
                "implementation_fingerprint": registration.implementation_manifest.implementation_fingerprint,
                "state_capability": registration.state_capability.value,
                "checkpoint_schema_version": registration.checkpoint_schema_version,
            }
        self._backends = {key: self._new(key) for key in self._entries}

    def _context(self, key: str) -> Context:
        numeric = self._entries[key][0].numeric
        if numeric.rounding == "CONTEXT":
            numeric = replace(numeric, rounding=ROUND_HALF_EVEN)
        return only_decimal_context(numeric)

    def _new(self, key: str) -> TradingBackend:
        definition, registration = self._entries[key]
        with localcontext(self._context(key)):
            backend = cast(OnlyTradingBackendFactory, registration.provider).create(definition, None)
        if not callable(getattr(backend, "update", None)) or getattr(backend, "definition", None) != definition:
            raise ValueError("TRADING_ALGORITHM_BACKEND_INVALID")
        if registration.state_capability is OnlyCalculationStateCapability.CHECKPOINTABLE and (
            type(getattr(backend, "checkpoint_schema_version", None)) is not int
            or getattr(backend, "checkpoint_schema_version", None) != registration.checkpoint_schema_version
            or not callable(getattr(backend, "capture_checkpoint", None))
            or not callable(getattr(backend, "restore_checkpoint", None))
        ):
            raise ValueError("TRADING_ALGORITHM_STATE_UNSUPPORTED")
        return cast(TradingBackend, backend)

    def update(self, key: str, inputs: dict[str, object]) -> dict[str, object]:
        if type(key) is not str or key not in self._entries:
            raise ValueError("TRADING_ALGORITHM_NODE_UNKNOWN")
        definition = self._entries[key][0]
        _values(inputs, definition.inputs)
        with localcontext(self._context(key)):
            outputs = self._backends[key].update(dict(inputs))
        if not isinstance(outputs, Mapping):
            raise ValueError("TRADING_ALGORITHM_PORT_MISMATCH")
        result = dict(outputs)
        _values(result, definition.outputs)
        return result

    def checkpoint(self) -> dict[str, Any]:
        nodes = {}
        for key, (_, registration) in self._entries.items():
            state = None
            if registration.state_capability is OnlyCalculationStateCapability.CHECKPOINTABLE:
                with localcontext(self._context(key)):
                    state = cast(CheckpointBackend, self._backends[key]).capture_checkpoint()
                # Fresh restoration proves the actual factory can consume what it captured.
                self._restored(key, state)
            nodes[key] = {**self._bindings[key], "state": state}
        return cast(dict[str, Any], json.loads(_json({"schema_version": 1, "nodes": nodes})))

    def _restored(self, key: str, state: object) -> TradingBackend:
        backend = self._new(key)
        if self._entries[key][1].state_capability is OnlyCalculationStateCapability.STATELESS:
            if state is not None:
                raise ValueError("TRADING_ALGORITHM_STATE_INVALID")
        else:
            encoded = _json(state)
            with localcontext(self._context(key)):
                cast(CheckpointBackend, backend).restore_checkpoint(json.loads(encoded))
                observed = cast(CheckpointBackend, backend).capture_checkpoint()
            if _json(observed) != encoded:
                raise ValueError("TRADING_ALGORITHM_STATE_ROUNDTRIP_MISMATCH")
        return backend

    def restore(self, checkpoint: dict[str, Any]) -> None:
        # Copy/detach before calling any mutable factory; install only after all checks.
        raw = json.loads(_json(checkpoint))
        if (
            type(raw) is not dict
            or set(raw) != {"schema_version", "nodes"}
            or type(raw["schema_version"]) is not int
            or raw["schema_version"] != 1
            or type(raw["nodes"]) is not dict
            or set(raw["nodes"]) != set(self._entries)
        ):
            raise ValueError("TRADING_ALGORITHM_CHECKPOINT_INVALID")
        candidates = {}
        for key, binding in self._bindings.items():
            entry = raw["nodes"][key]
            if type(entry) is not dict or set(entry) != {*binding, "state"}:
                raise ValueError("TRADING_ALGORITHM_CHECKPOINT_INVALID")
            if _json({name: entry[name] for name in binding}) != _json(binding):
                raise ValueError("TRADING_ALGORITHM_CHECKPOINT_BINDING_MISMATCH")
            candidates[key] = self._restored(key, entry["state"])
        self._backends = candidates
