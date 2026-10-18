"""Atomic invocation of the registered Python SMA; no algorithm in Rust/transport."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from functools import cache
from typing import Any, cast

from onlyalpha_plugin_indicators.registration import (
    OnlyIndicatorBackendRequest,
    OnlyStandardBackendFactory,
    registrations,
)
from onlyalpha_plugin_indicators.standard import OnlyStandardBarIndicator

from onlyalpha.calculation.decimal_execution import only_decimal_context
from onlyalpha.calculation.definition import OnlyCalculationBackendKind, OnlyCalculationDefinition
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration
from onlyalpha.domain.errors import OnlyDomainError
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.identifiers import OnlyIndicatorId
from onlyalpha_calculation_worker.contracts import (
    MAX_BATCH,
    MAX_INSTANCES,
    MAX_U64,
    binding,
    component_definition,
    decode,
    digest,
    encode,
    exact,
    input_context,
    integer,
    sha,
)


@cache
def registration() -> OnlyCalculationBackendRegistration:
    return next(
        r
        for r in registrations()
        if r.type_definition.type_id == "onlyalpha.indicator.sma"
        and r.type_definition.semantic_version == "1"
        and r.backend is OnlyCalculationBackendKind.TRADING
    )


def _definition(parameters: dict[str, Any]) -> OnlyCalculationDefinition:
    if type(parameters) is not dict or set(parameters) - {"period", "price_field"}:
        raise ValueError("PARAMETERS_INVALID")
    if "period" in parameters:
        integer(parameters["period"], 1, 4096)
    if "price_field" in parameters and type(parameters["price_field"]) is not str:
        raise ValueError("PARAMETERS_INVALID")
    factory = cast(OnlyStandardBackendFactory, registration().provider)
    return factory.resolve_definition(parameters)


def resolve(parameters: dict[str, Any]) -> dict[str, Any]:
    native = _definition(parameters)
    record = component_definition(native)
    manifest = registration().implementation_manifest
    assert manifest is not None
    return {
        "schema_version": 1,
        "definition": record,
        "definition_fingerprint": digest(encode(record)),
        "native_definition": native.fingerprint,
        "implementation": manifest.implementation_fingerprint,
    }


def _new(parameters: dict[str, Any], scope: str, bar_type: OnlyBarType) -> OnlyStandardBarIndicator:
    factory = cast(OnlyStandardBackendFactory, registration().provider)
    return cast(
        OnlyStandardBarIndicator,
        factory.create(_definition(parameters), OnlyIndicatorBackendRequest(OnlyIndicatorId(scope), bar_type)),
    )


def _finite(value: object) -> None:
    if type(value) is not str or len(value) > 4096:
        raise ValueError("STATE_DECIMAL")
    decimal = Decimal(value)
    if not decimal.is_finite() or abs(decimal.adjusted()) > 4096:
        raise ValueError("STATE_DECIMAL")


@dataclass
class _Instance:
    binding: dict[str, Any]
    parameters: dict[str, Any]
    indicator: OnlyStandardBarIndicator
    revision: int = 0
    fresh: bool = True

    def cursor(self) -> dict[str, Any]:
        state = self.indicator.capture_checkpoint()
        assert isinstance(state, dict)
        return {
            "schema_version": 1,
            "binding": decode(encode(self.binding)),
            "revision": self.revision,
            "samples": state["samples"],
            "last_event_ns": None if state["last_event_ns"] is None else str(state["last_event_ns"]),
        }

    def candidate(self) -> OnlyStandardBarIndicator:
        new = _new(self.parameters, self.binding["scope"], self.indicator.bar_type)
        new.restore_checkpoint(self.indicator.capture_checkpoint())
        return new


def _checkpoint_state(instance: _Instance, payload: object) -> tuple[dict[str, Any], dict[str, Any]]:
    """One admissibility boundary for fresh, updated, reset and restored state."""
    scope = instance.binding["scope"]
    envelope = exact(payload, {"schema_version", "cursor", "plugin_state"})
    if type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1:
        raise ValueError("CHECKPOINT_SCHEMA")
    cursor = exact(envelope["cursor"], {"schema_version", "binding", "revision", "samples", "last_event_ns"})
    if (
        type(cursor["schema_version"]) is not int
        or cursor["schema_version"] != 1
        or binding(cursor["binding"]) != instance.binding
    ):
        raise ValueError("CHECKPOINT_CONTEXT")
    samples, restored_revision = integer(cursor["samples"]), integer(cursor["revision"])
    state = exact(
        envelope["plugin_state"],
        {"ema", "last_event_ns", "previous_close", "samples", "snapshot", "snapshot_type", "true_ranges", "values"},
    )
    period = instance.indicator.config.period
    if (
        type(state["values"]) is not list
        or len(state["values"]) != min(samples, period + 1)
        or state["ema"] is not None
        or state["true_ranges"] != []
        or state["snapshot_type"] != "OnlyScalarIndicatorSnapshot"
        or integer(state["samples"]) != samples
    ):
        raise ValueError("CHECKPOINT_STATE")
    for value in state["values"]:
        _finite(value)
    snapshot = exact(state["snapshot"], {"indicator_id", "ts_event_ns", "samples", "value", "ready"})
    event = state["last_event_ns"]
    if event is not None and (type(event) is not int or len(str(event)) > 128):
        raise ValueError("CHECKPOINT_TIME")
    if (
        (samples == 0) != (event is None)
        or cursor["last_event_ns"] != (None if event is None else str(event))
        or (restored_revision == 0 and samples != 0)
    ):
        raise ValueError("CHECKPOINT_CURSOR")
    if (
        snapshot["indicator_id"] != scope
        or type(snapshot["ts_event_ns"]) is not type(event)
        or snapshot["ts_event_ns"] != event
        or integer(snapshot["samples"]) != samples
        or type(snapshot["ready"]) is not bool
        or snapshot["ready"] != (samples >= period)
    ):
        raise ValueError("CHECKPOINT_SNAPSHOT")
    if (snapshot["value"] is None) != (samples == 0):
        raise ValueError("CHECKPOINT_VALUE")
    if snapshot["value"] is not None:
        _finite(snapshot["value"])
    if state["previous_close"] is not None:
        _finite(state["previous_close"])
    if (state["previous_close"] is None) != (samples == 0):
        raise ValueError("CHECKPOINT_UNUSED_STATE")
    encode(envelope)
    return cursor, state


class Backend:
    def __init__(self, generation: str, artifact: str) -> None:
        self.generation, self.artifact = sha(generation), sha(artifact)
        self._instances: dict[str, _Instance] = {}

    def create(
        self, raw_binding: object, definition: object, bar_type_record: object, parameters: dict[str, Any], source: str
    ) -> dict[str, Any]:
        bound = binding(raw_binding)
        scope = bound["scope"]
        if scope in self._instances or len(self._instances) >= MAX_INSTANCES:
            raise ValueError("INSTANCE_UNAVAILABLE")
        resolved = resolve(parameters)
        expected = [
            self.generation,
            self.artifact,
            resolved["definition_fingerprint"],
            resolved["native_definition"],
            resolved["implementation"],
            input_context(bar_type_record, source),
        ]
        if bound["digests"] != expected or definition != resolved["definition"]:
            raise ValueError("BINDING_MISMATCH")
        if type(bar_type_record) is not dict:
            raise ValueError("BAR_TYPE_INVALID")
        try:
            bar_type = OnlyBarType.from_dict(bar_type_record)
        except OnlyDomainError as exc:
            raise ValueError("BAR_TYPE_INVALID") from exc
        instance = _Instance(bound, decode(encode(parameters)), _new(parameters, scope, bar_type))
        _checkpoint_state(
            instance,
            {"schema_version": 1, "cursor": instance.cursor(), "plugin_state": instance.indicator.capture_checkpoint()},
        )
        self._instances[scope] = instance
        return instance.cursor()

    def _get(self, scope: str, revision: int) -> _Instance:
        integer(revision)
        instance = self._instances.get(scope)
        if instance is None or revision != instance.revision:
            raise ValueError("INSTANCE_REVISION_MISMATCH")
        return instance

    def update(self, scope: str, revision: int, raw_bars: list[bytes], expected_digest: str) -> dict[str, Any]:
        instance = self._get(scope, revision)
        if (
            not 1 <= len(raw_bars) <= MAX_BATCH
            or revision == MAX_U64
            or digest(b"".join(raw_bars)) != sha(expected_digest)
        ):
            raise ValueError("BATCH_INVALID")
        cursor = instance.cursor()
        integer(cursor["samples"] + len(raw_bars))
        last = None if cursor["last_event_ns"] is None else int(cursor["last_event_ns"])
        bars = []
        for raw in raw_bars:
            record = decode(raw)
            if type(record) is not dict:
                raise ValueError("BAR_INVALID")
            try:
                bar = OnlyBar.from_dict(record)
            except OnlyDomainError as exc:
                raise ValueError("BAR_INVALID") from exc
            event = OnlyTimestamp.from_datetime(bar.ts_event).to_unix_nanos()
            if (
                bar.bar_type != instance.indicator.bar_type
                or not bar.is_closed
                or bar.ts_event != bar.bar_end
                or (last is not None and event <= last)
            ):
                raise ValueError("BAR_ORDER_OR_CONTEXT")
            bars.append(bar)
            last = event
        candidate = instance.candidate()
        points = []
        numeric = replace(candidate.definition.numeric, rounding="ROUND_HALF_EVEN")
        with localcontext(only_decimal_context(numeric)):
            for bar in bars:
                candidate.update_bar(bar)
                row = dict(candidate.snapshot().to_dict())
                exact(row, {"indicator_id", "ts_event_ns", "samples", "value", "ready"})
                integer(row["samples"])
                if type(row["ready"]) is not bool or row["indicator_id"] != scope:
                    raise ValueError("OUTPUT_INVALID")
                if row["value"] is not None:
                    _finite(row["value"])
                points.append(
                    {
                        "ts_event_ns": str(row["ts_event_ns"]),
                        "samples": row["samples"],
                        "value": row["value"],
                        "ready": row["ready"],
                    }
                )
        proposed = _Instance(instance.binding, instance.parameters, candidate, revision + 1, False)
        result = {"cursor": proposed.cursor(), "input_digest": expected_digest, "points": points}
        encode(result)  # Bound response before committing candidate state.
        _checkpoint_state(
            proposed, {"schema_version": 1, "cursor": proposed.cursor(), "plugin_state": candidate.capture_checkpoint()}
        )
        self._instances[scope] = proposed
        return result

    def reset(self, scope: str, revision: int) -> dict[str, Any]:
        instance = self._get(scope, revision)
        integer(revision + 1)
        proposed = _Instance(
            instance.binding,
            instance.parameters,
            _new(instance.parameters, scope, instance.indicator.bar_type),
            revision + 1,
            False,
        )
        _checkpoint_state(
            proposed,
            {"schema_version": 1, "cursor": proposed.cursor(), "plugin_state": proposed.indicator.capture_checkpoint()},
        )
        self._instances[scope] = proposed
        return proposed.cursor()

    def capture(self, scope: str, revision: int) -> dict[str, Any]:
        instance = self._get(scope, revision)
        return cast(
            dict[str, Any],
            decode(
                encode(
                    {
                        "schema_version": 1,
                        "cursor": instance.cursor(),
                        "plugin_state": instance.indicator.capture_checkpoint(),
                    }
                )
            ),
        )

    def restore(self, scope: str, revision: int, raw: bytes, expected_digest: str) -> dict[str, Any]:
        instance = self._get(scope, revision)
        if not instance.fresh or digest(raw) != sha(expected_digest):
            raise ValueError("RESTORE_NOT_ADMITTED")
        cursor, state = _checkpoint_state(instance, decode(raw))
        candidate = _new(instance.parameters, scope, instance.indicator.bar_type)
        candidate.restore_checkpoint(state)
        if candidate.capture_checkpoint() != state:
            raise ValueError("CHECKPOINT_RECAPTURE")
        proposed = _Instance(instance.binding, instance.parameters, candidate, integer(cursor["revision"]), False)
        if proposed.cursor() != cursor:
            raise ValueError("CHECKPOINT_CURSOR")
        self._instances[scope] = proposed
        return proposed.cursor()

    def close(self, scope: str, revision: int) -> dict[str, Any]:
        instance = self._get(scope, revision)
        result = instance.cursor()
        del self._instances[scope]
        return result
