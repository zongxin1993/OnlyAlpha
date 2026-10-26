"""Closed registered TRADING node operations for the Rust Strategy component."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import localcontext
from enum import Enum
from functools import cache
from typing import Any, cast

from onlyalpha_plugin_indicators.registration import OnlyIndicatorBackendRequest
from onlyalpha_plugin_indicators.registration import registrations as indicators
from onlyalpha_plugin_operators.registration import registrations as operators
from onlyalpha_plugin_operators.trading import OnlyOfficialTradingStatefulOperatorBackend

from onlyalpha.algorithm.type_declaration import type_declaration
from onlyalpha.calculation.decimal_execution import only_decimal_context
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDefinition,
    OnlyCalculationReference,
    OnlyCalculationTypeReference,
    OnlyInputDefinition,
    OnlyOutputDefinition,
    only_calculation_execution_shape,
    only_calculation_scalar_from_dict,
)
from onlyalpha.calculation.implementation import OnlyCalculationStateCapability
from onlyalpha.calculation.registry import (
    OnlyCalculationBackendRegistration,
    OnlyCalculationRegistry,
    OnlyTradingCalculationBackendResolver,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.identifiers import OnlyIndicatorId
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives
from onlyalpha.strategy.execution import only_invoke_trading_calculation
from onlyalpha_calculation_worker.contracts import (
    MAX_INSTANCES,
    _plain,
    binding,
    component_definition,
    decode,
    digest,
    encode,
    exact,
    integer,
    scalar,
    sha,
)


@cache
def registry() -> OnlyCalculationRegistry:
    result = OnlyCalculationRegistry()
    for registration in (*indicators(), *operators()):
        if registration.backend is OnlyCalculationBackendKind.TRADING:
            result.register(registration)
    only_register_trading_predicate_primitives(result)
    return result


def _resolve(
    request: object, calculations: OnlyCalculationRegistry
) -> tuple[OnlyCalculationDefinition, OnlyCalculationBackendRegistration, dict[str, Any]]:
    row = exact(request, {"schema_version", "op", "reference", "parameters", "input_bindings"})
    if type(row["schema_version"]) is not int or row["schema_version"] != 1 or row["op"] != "RESOLVE":
        raise ValueError("NODE_SCHEMA")
    reference = OnlyCalculationTypeReference.from_dict(exact(row["reference"], {"kind", "type_id", "semantic_version"}))
    if type(row["parameters"]) is not dict or type(row["input_bindings"]) is not dict:
        raise ValueError("NODE_DEFINITION")
    parameters = {name: only_calculation_scalar_from_dict(value) for name, value in row["parameters"].items()}
    references = {}
    for name, value in row["input_bindings"].items():
        r = exact(value, {"node_fingerprint", "output_name", "source"})
        if r["node_fingerprint"] is not None:
            sha(r["node_fingerprint"])
        references[name] = OnlyCalculationReference(**r)
    native = calculations.rematerialize_definition(reference, parameters, references)
    registration = calculations.resolve(
        reference.kind, reference.type_id, reference.semantic_version, OnlyCalculationBackendKind.TRADING
    )
    if (
        only_calculation_execution_shape(native).value != "TIME_SERIES"
        or registration.implementation_manifest is None
        or registration.state_capability
        not in (OnlyCalculationStateCapability.STATELESS, OnlyCalculationStateCapability.CHECKPOINTABLE)
    ):
        raise ValueError("NODE_UNAVAILABLE")
    definition = component_definition(native)
    descriptor = {
        "schema_version": 1,
        "definition": definition,
        "definition_fingerprint": digest(encode(definition)),
        "native_definition": native.fingerprint,
        "implementation": registration.implementation_manifest.implementation_fingerprint,
        "state_capability": registration.state_capability.value,
        "checkpoint_schema_version": registration.checkpoint_schema_version,
    }
    return native, registration, descriptor


def _values(values: object, ports: Sequence[OnlyInputDefinition | OnlyOutputDefinition]) -> dict[str, object]:
    if type(values) is not dict or set(values) != {p.name for p in ports}:
        raise ValueError("NODE_PORTS")
    result: dict[str, object] = {}
    for p in ports:
        tagged = exact(values[p.name], {"type", "value"})
        value = only_calculation_scalar_from_dict(tagged)
        if (
            scalar(value) != tagged
            or (value is None and not p.nullable)
            or (value is not None and tagged["type"] != p.data_type.value)
        ):
            raise ValueError("NODE_SCALAR")
        result[p.name] = value
    return result


@dataclass
class _Node:
    binding: dict[str, Any]
    native: OnlyCalculationDefinition
    registration: OnlyCalculationBackendRegistration
    descriptor: dict[str, Any]
    bar_type: OnlyBarType
    instance: Any
    calculations: OnlyCalculationRegistry
    samples: int = 0
    receipt: dict[str, Any] | None = None

    def cursor(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "binding": self.binding,
            "revision": self.samples,
            "samples": self.samples,
            "last_event_ns": None if self.receipt is None else self.receipt["cursor"]["last_event_ns"],
        }

    def fresh(self) -> Any:
        return OnlyTradingCalculationBackendResolver(self.calculations).create(
            self.native, OnlyIndicatorBackendRequest(OnlyIndicatorId(self.binding["scope"]), self.bar_type)
        )

    def plugin(self, instance: Any) -> object:
        if self.registration.state_capability is OnlyCalculationStateCapability.STATELESS:
            return None
        return _plain(instance.capture_checkpoint())

    def validate_cut(self) -> None:
        if self.receipt is None:
            if self.samples != 0:
                raise ValueError("NODE_EMPTY_CURSOR")
        if isinstance(self.instance, OnlyBarIndicator):
            snapshot = self.instance.snapshot()
            if snapshot.samples != self.samples:
                raise ValueError("NODE_NATIVE_SAMPLES")
            if self.receipt is not None:
                values = {}
                for output in self.native.outputs:
                    value = getattr(snapshot, output.name)
                    values[output.name] = scalar(value.value if isinstance(value, Enum) else value)
                if (
                    snapshot.ts_event is None
                    or str(snapshot.ts_event.unix_nanos) != self.receipt["cursor"]["last_event_ns"]
                    or snapshot.ready != self.receipt["ready"]
                    or values != self.receipt["outputs"]
                ):
                    raise ValueError("NODE_NATIVE_RECEIPT")
            elif snapshot.ts_event is not None or snapshot.ready:
                raise ValueError("NODE_NATIVE_EMPTY")
        elif isinstance(self.instance, OnlyOfficialTradingStatefulOperatorBackend):
            period = int(str(self.native.parameters["period"]))
            capacity = period + 1 if self.native.type_id.endswith((".delay", ".delta")) else period
            state = exact(self.plugin(self.instance), {"inputs"})
            if any(len(window) != min(self.samples, capacity) for window in state["inputs"].values()):
                raise ValueError("NODE_NATIVE_WINDOW")
        if self.receipt is not None and not isinstance(self.instance, OnlyBarIndicator):
            if self.receipt["ready"] != (self.samples >= self.native.warmup.minimum_observations):
                raise ValueError("NODE_DECLARED_READINESS")

    def checkpoint(self) -> dict[str, Any]:
        self.validate_cut()
        plugin_state = self.plugin(self.instance)
        return {
            "schema_version": 1,
            "binding": self.binding,
            "cursor": self.cursor(),
            "receipt": self.receipt,
            "plugin_state": plugin_state,
            "state_fingerprint": digest(encode(plugin_state)),
            "state_capability": self.descriptor["state_capability"],
            "checkpoint_schema_version": self.descriptor["checkpoint_schema_version"],
            "definition_fingerprint": self.descriptor["definition_fingerprint"],
        }

    def candidate(self, payload: object) -> Any:
        candidate = self.fresh()
        if self.registration.state_capability is OnlyCalculationStateCapability.STATELESS:
            if payload is not None:
                raise ValueError("STATELESS_PAYLOAD")
        else:
            if getattr(candidate, "checkpoint_schema_version", None) != self.registration.checkpoint_schema_version:
                raise ValueError("CHECKPOINT_SCHEMA")
            candidate.restore_checkpoint(payload)
        if self.plugin(candidate) != payload:
            raise ValueError("CHECKPOINT_ROUNDTRIP")
        return candidate


class NodeBackend:
    def __init__(self, generation: str, artifact: str, *, calculations: OnlyCalculationRegistry | None = None):
        self.generation = sha(generation)
        self.artifact = sha(artifact)
        self.nodes: dict[str, _Node] = {}
        self.calculations = calculations if calculations is not None else registry()

    def resolve(self, request: object) -> dict[str, Any]:
        native, registration, descriptor = _resolve(request, self.calculations)
        return {
            "schema_version": 2,
            "descriptor": descriptor,
            "product_definition": decode(only_canonical_json(native.to_dict()).encode("utf-8")),
            "type_declaration": type_declaration(registration.type_definition),
        }

    def create(self, request: object) -> dict[str, Any]:
        r = exact(
            request, {"schema_version", "op", "binding", "resolution", "bar_type", "source", "strategy_fingerprint"}
        )
        if type(r["schema_version"]) is not int or r["schema_version"] != 1 or r["op"] != "CREATE":
            raise ValueError("NODE_SCHEMA")
        b = binding(r["binding"])
        native, registration, descriptor = _resolve(r["resolution"], self.calculations)
        bar_type = OnlyBarType.from_dict(r["bar_type"])
        context = digest(
            encode(
                {
                    "schema_version": 1,
                    "bar_type": bar_type.to_dict(),
                    "source_fingerprint": sha(r["source"]),
                    "strategy_fingerprint": sha(r["strategy_fingerprint"]),
                }
            )
        )
        if (
            b["digests"]
            != [
                self.generation,
                self.artifact,
                descriptor["definition_fingerprint"],
                descriptor["native_definition"],
                descriptor["implementation"],
                context,
            ]
            or b["scope"] in self.nodes
            or len(self.nodes) >= MAX_INSTANCES
        ):
            raise ValueError("NODE_BINDING")
        node = _Node(b, native, registration, descriptor, bar_type, None, self.calculations)
        node.instance = node.fresh()
        node.candidate(node.plugin(node.instance))
        checkpoint = node.checkpoint()
        encode(checkpoint)
        self.nodes[b["scope"]] = node
        return checkpoint

    def update(self, request: object) -> dict[str, Any]:
        r = exact(request, {"schema_version", "op", "scope", "revision", "bar", "inputs", "input_digest"})
        if type(r["schema_version"]) is not int or r["schema_version"] != 1 or r["op"] != "UPDATE":
            raise ValueError("NODE_SCHEMA")
        node = self.nodes[r["scope"]]
        if integer(r["revision"]) != node.samples or node.samples == 2**64 - 1:
            raise ValueError("NODE_REVISION")
        bar = OnlyBar.from_dict(r["bar"])
        event = str(OnlyTimestamp.from_datetime(bar.bar_end).unix_nanos)
        if (
            bar.bar_type != node.bar_type
            or not bar.is_closed
            or bar.ts_event != bar.bar_end
            or bar.revision != 0
            or node.receipt is not None
            and int(event) <= int(node.receipt["cursor"]["last_event_ns"])
        ):
            raise ValueError("NODE_BAR")
        values = _values(r["inputs"], node.native.inputs)
        input_record = {"schema_version": 1, "binding": node.binding, "bar": bar.to_dict(), "inputs": r["inputs"]}
        if digest(encode(input_record)) != sha(r["input_digest"]):
            raise ValueError("NODE_INPUT_DIGEST")
        # CONTEXT is bound by the same explicit worker numeric policy as the SMA lane.
        numeric = (
            replace(node.native.numeric, rounding="ROUND_HALF_EVEN")
            if node.native.numeric.rounding == "CONTEXT"
            else node.native.numeric
        )
        with localcontext(only_decimal_context(numeric)):
            candidate = node.candidate(node.plugin(node.instance))
            outputs = only_invoke_trading_calculation(candidate, node.native.outputs, bar, values)
            tagged = {name: scalar(value) for name, value in outputs.items()}
            _values(tagged, node.native.outputs)
            ready = (
                candidate.snapshot().ready
                if isinstance(candidate, OnlyBarIndicator)
                else node.samples + 1 >= node.native.warmup.minimum_observations
            )
            receipt = {
                "cursor": {
                    **node.cursor(),
                    "samples": node.samples + 1,
                    "revision": node.samples + 1,
                    "last_event_ns": event,
                },
                "input_digest": r["input_digest"],
                "outputs": tagged,
                "ready": ready,
                "quality_flags": [],
            }
            encode(receipt)
            node.candidate(node.plugin(candidate))
        proposed = replace(node, instance=candidate, samples=node.samples + 1, receipt=receipt)
        checkpoint = proposed.checkpoint()
        encode(checkpoint)
        acknowledgment = {"receipt": receipt, "state_fingerprint": checkpoint["state_fingerprint"]}
        encode(acknowledgment)
        self.nodes[r["scope"]] = proposed
        return cast(dict[str, Any], decode(encode(acknowledgment)))

    def capture(self, scope: str) -> dict[str, Any]:
        return cast(dict[str, Any], decode(encode(self.nodes[scope].checkpoint())))

    def restore(self, scope: str, payload: object) -> dict[str, Any]:
        node = self.nodes[scope]
        if node.samples != 0 or node.receipt is not None:
            raise ValueError("FRESH_NODE_REQUIRED")
        r = exact(
            payload,
            {
                "schema_version",
                "binding",
                "cursor",
                "receipt",
                "plugin_state",
                "state_fingerprint",
                "state_capability",
                "checkpoint_schema_version",
                "definition_fingerprint",
            },
        )
        if type(r["schema_version"]) is not int:
            raise ValueError("NODE_CHECKPOINT_SCHEMA")
        expected = node.checkpoint()
        for key in (
            "schema_version",
            "binding",
            "state_capability",
            "checkpoint_schema_version",
            "definition_fingerprint",
        ):
            if r[key] != expected[key]:
                raise ValueError("NODE_CHECKPOINT_BINDING")
        cursor = exact(r["cursor"], {"schema_version", "binding", "revision", "samples", "last_event_ns"})
        samples = integer(cursor["samples"])
        if (
            type(cursor["schema_version"]) is not int
            or cursor["schema_version"] != 1
            or cursor["binding"] != node.binding
            or integer(cursor["revision"]) != samples
        ):
            raise ValueError("NODE_CHECKPOINT_CURSOR")
        if samples == 0:
            if cursor["last_event_ns"] is not None or r["receipt"] is not None:
                raise ValueError("NODE_CHECKPOINT_EMPTY")
        else:
            receipt = exact(r["receipt"], {"cursor", "input_digest", "outputs", "ready", "quality_flags"})
            event = cursor["last_event_ns"]
            if (
                type(event) is not str
                or len(event) > 128
                or str(int(event)) != event
                or receipt["cursor"] != cursor
                or type(receipt["ready"]) is not bool
                or receipt["quality_flags"] != []
            ):
                raise ValueError("NODE_CHECKPOINT_RECEIPT")
            sha(receipt["input_digest"])
            _values(receipt["outputs"], node.native.outputs)
        if sha(r["state_fingerprint"]) != digest(encode(r["plugin_state"])):
            raise ValueError("NODE_NATIVE_COMMITMENT")
        candidate = node.candidate(r["plugin_state"])
        # Fresh atomic replacement after every owning reader has accepted the cut.
        proposed = replace(node, instance=candidate, samples=samples, receipt=r["receipt"])
        result = cast(dict[str, Any], decode(encode(proposed.checkpoint())))
        self.nodes[scope] = proposed
        return result

    def dispatch(self, request: object) -> dict[str, Any]:
        if type(request) is not dict:
            raise ValueError("NODE_REQUEST")
        op = request.get("op")
        if op == "RESOLVE":
            return self.resolve(request)
        if op == "CREATE":
            return self.create(request)
        if op == "UPDATE":
            return self.update(request)
        if op in ("CHECKPOINT", "RESTORE", "CLOSE"):
            keys = {"schema_version", "op", "scope"} | ({"checkpoint"} if op == "RESTORE" else set())
            r = exact(request, keys)
            if type(r["schema_version"]) is not int or r["schema_version"] != 1:
                raise ValueError("NODE_SCHEMA")
            if op == "RESTORE":
                return self.restore(r["scope"], r["checkpoint"])
            if op == "CLOSE":
                del self.nodes[r["scope"]]
                return {"schema_version": 1}
            return self.capture(r["scope"])
        raise ValueError("NODE_OPERATION")
