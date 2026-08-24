"""One Strategy Revision resolver and incremental Calculation TRADING execution form."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from onlyalpha.calculation.definition import OnlyCalculationBackendKind, OnlyOutputDefinition
from onlyalpha.calculation.implementation import OnlyCalculationStateCapability
from onlyalpha.calculation.registry import (
    OnlyCalculationBackendRegistration,
    OnlyCalculationRegistry,
    OnlyTradingCalculationBackendResolver,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.enums import OnlyAdjustmentType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.identifiers import OnlyIndicatorId
from onlyalpha.strategy.errors import OnlyStrategyResolutionError
from onlyalpha.strategy.revision import OnlyStrategyFingerprint, OnlyStrategyRevision, OnlyStrategySignalBinding
from onlyalpha.strategy.store import OnlyStrategyRevisionReader


@dataclass(frozen=True, slots=True)
class OnlyStrategyObservationKey:
    instrument_id: str
    bar_step: int
    bar_aggregation: str
    price_type: str
    aggregation_source: str
    adjustment_type: str
    bar_end_ns: int

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self)


@dataclass(frozen=True, slots=True)
class OnlyStrategyDecision:
    strategy_fingerprint: str
    instrument_id: str
    observation_key: OnlyStrategyObservationKey
    observation_fingerprint: str
    decision_time: OnlyTimestamp
    eligibility: bool
    entry: bool
    exit: bool
    schema_version: int = 1

    def __post_init__(self) -> None:
        OnlyStrategyFingerprint(self.strategy_fingerprint)
        if self.schema_version != 1:
            raise ValueError("unsupported Strategy Decision schema")


@dataclass(frozen=True, slots=True)
class OnlyStrategyExecutionPlan:
    revision: OnlyStrategyRevision
    calculations: OnlyCalculationRegistry

    @property
    def strategy_fingerprint(self) -> OnlyStrategyFingerprint:
        return self.revision.strategy_fingerprint

    def new_executor(self) -> OnlyStrategyIncrementalExecutor:
        return OnlyStrategyIncrementalExecutor(self)


class OnlyStrategyExecutionResolver:
    def __init__(self, strategies: OnlyStrategyRevisionReader, calculations: OnlyCalculationRegistry) -> None:
        self._strategies = strategies
        self._calculations = calculations

    def resolve(self, strategy_fingerprint: OnlyStrategyFingerprint | str) -> OnlyStrategyExecutionPlan:
        try:
            revision = self._strategies.load_verified(strategy_fingerprint)
            if (
                revision.market_input_contract.adjustment_type is not OnlyAdjustmentType.RAW
                or revision.market_input_contract.adjustment_reference is not None
            ):
                raise OnlyStrategyResolutionError(
                    "STRATEGY_OBSERVATION_NOT_ADMITTED",
                    "P9.0 Trading Strategy input must be RAW without an adjustment reference",
                )
            expected = {item.node_fingerprint: item for item in revision.implementation_bindings}
            for node in revision.decision_graph.nodes:
                binding = expected[node.fingerprint]
                registration = self._calculations.resolve(
                    node.definition.kind,
                    node.definition.type_id,
                    node.definition.semantic_version,
                    OnlyCalculationBackendKind.TRADING,
                )
                manifest = registration.implementation_manifest
                if (
                    manifest is None
                    or manifest.implementation_fingerprint != binding.trading_implementation_fingerprint
                ):
                    raise OnlyStrategyResolutionError(
                        "IMPLEMENTATION_IDENTITY_MISMATCH",
                        f"{node.definition.type_id}@{node.definition.semantic_version}:TRADING",
                    )
                if registration.state_capability is None:
                    raise OnlyStrategyResolutionError(
                        "CALCULATION_STATE_CAPABILITY_UNRESOLVED",
                        f"{node.definition.type_id}@{node.definition.semantic_version}",
                    )
            return OnlyStrategyExecutionPlan(revision, self._calculations)
        except OnlyStrategyResolutionError:
            raise
        except Exception as exc:
            raise OnlyStrategyResolutionError("STRATEGY_RESOLUTION_FAILED", type(exc).__name__) from exc


@dataclass(frozen=True, slots=True)
class _TradingIndicatorRequest:
    indicator_id: OnlyIndicatorId
    bar_type: OnlyBarType


class OnlyStrategyIncrementalExecutor:
    def __init__(self, plan: OnlyStrategyExecutionPlan) -> None:
        self._plan = plan
        self._resolver = OnlyTradingCalculationBackendResolver(plan.calculations)
        self._instances: dict[tuple[str, str], object] = {}
        self._last: dict[str, OnlyStrategyDecision] = {}

    @property
    def last_decisions(self) -> tuple[OnlyStrategyDecision, ...]:
        return tuple(self._last[key] for key in sorted(self._last))

    def execute(self, bar: OnlyBar) -> OnlyStrategyDecision:
        revision = self._plan.revision
        contract = revision.market_input_contract
        instrument = str(bar.instrument_id)
        if bar.instrument_id not in set(revision.universe.instruments):
            raise OnlyStrategyResolutionError("STRATEGY_OBSERVATION_NOT_ADMITTED", "instrument is outside Universe")
        if not bar.is_closed:
            raise OnlyStrategyResolutionError("STRATEGY_OBSERVATION_NOT_FINAL", instrument)
        if (
            bar.bar_type.specification != contract.bar_specification
            or bar.bar_type.aggregation_source is not contract.aggregation_source
            or bar.adjustment_type is not contract.adjustment_type
        ):
            raise OnlyStrategyResolutionError("STRATEGY_OBSERVATION_NOT_ADMITTED", "Market Input Contract mismatch")
        key = only_strategy_observation_key(bar)
        observation_fingerprint = only_strategy_observation_fingerprint(bar)
        previous = self._last.get(instrument)
        if previous is not None and previous.observation_key == key:
            if previous.observation_fingerprint != observation_fingerprint:
                raise OnlyStrategyResolutionError(
                    "CORRECTED_FINAL_BAR_UNSUPPORTED",
                    "P9.0 does not roll back finalized Strategy state",
                )
            return previous
        if previous is not None and key.bar_end_ns <= previous.observation_key.bar_end_ns:
            raise OnlyStrategyResolutionError("STRATEGY_OBSERVATION_OUT_OF_ORDER", instrument)
        outputs: dict[tuple[str, str], object] = {}
        for node in revision.decision_graph.ordered_nodes:
            definition = node.definition
            inputs = {
                name: (
                    _bar_source(bar, reference.source)
                    if reference.source is not None
                    else outputs[(str(reference.node_fingerprint), reference.output_name)]
                )
                for name, reference in definition.input_bindings.items()
            }
            instance = self._instance(instrument, node.fingerprint, definition, bar.bar_type)
            values = only_invoke_trading_calculation(instance, definition.outputs, bar, inputs)
            for output in definition.outputs:
                if output.name not in values:
                    raise OnlyStrategyResolutionError(
                        "TRADING_BACKEND_OUTPUT_INVALID",
                        f"{definition.type_id}.{output.name}",
                    )
                outputs[(node.fingerprint, output.name)] = values[output.name]
        signals = revision.signal_semantics
        decision = OnlyStrategyDecision(
            str(revision.strategy_fingerprint),
            instrument,
            key,
            observation_fingerprint,
            OnlyTimestamp.from_datetime(bar.ts_event),
            _decision(outputs, signals.eligibility),
            _decision(outputs, signals.entry),
            _decision(outputs, signals.exit),
        )
        self._last[instrument] = decision
        return decision

    def capture_checkpoint(self) -> Mapping[str, object]:
        instances: dict[str, object] = {}
        for (instrument, node), instance in sorted(self._instances.items()):
            registration = self._registration(node)
            if registration.state_capability is OnlyCalculationStateCapability.STATELESS:
                continue
            capture = getattr(instance, "capture_checkpoint", None)
            if not callable(capture):
                raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_UNSUPPORTED", node)
            schema_version = registration.checkpoint_schema_version
            assert schema_version is not None
            instances[f"{instrument}|{node}"] = {
                "participant_fingerprint": self._participant_fingerprint(instrument, node),
                "schema_version": schema_version,
                "payload": capture(),
            }
        return {
            "schema_version": 2,
            "instances": instances,
            "last_decisions": {
                instrument: _decision_to_checkpoint(decision) for instrument, decision in sorted(self._last.items())
            },
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema_version",
            "instances",
            "last_decisions",
        }:
            raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "invalid checkpoint fields")
        if (
            payload["schema_version"] != 2
            or not isinstance(payload["instances"], Mapping)
            or not isinstance(payload["last_decisions"], Mapping)
        ):
            raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "unsupported checkpoint")
        restored: dict[str, OnlyStrategyDecision] = {}
        for instrument, raw in payload["last_decisions"].items():
            if not isinstance(instrument, str):
                raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "invalid instrument")
            decision = _decision_from_checkpoint(raw)
            if decision.instrument_id != instrument:
                raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "instrument mismatch")
            if decision.strategy_fingerprint != str(self._plan.strategy_fingerprint):
                raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "Strategy identity mismatch")
            if OnlyInstrumentId.parse(instrument) not in set(self._plan.revision.universe.instruments):
                raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "instrument outside Universe")
            restored[instrument] = decision
        checkpointable_nodes = tuple(
            node.fingerprint
            for node in self._plan.revision.decision_graph.nodes
            if self._registration(node.fingerprint).state_capability is OnlyCalculationStateCapability.CHECKPOINTABLE
        )
        expected_participants = {f"{instrument}|{node}" for instrument in restored for node in checkpointable_nodes}
        if set(payload["instances"]) != expected_participants:
            raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "checkpoint participant set differs")
        nodes = {item.fingerprint: item.definition for item in self._plan.revision.decision_graph.nodes}
        contract = self._plan.revision.market_input_contract
        for key, raw in payload["instances"].items():
            if (
                not isinstance(key, str)
                or not isinstance(raw, Mapping)
                or set(raw) != {"participant_fingerprint", "schema_version", "payload"}
            ):
                raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "invalid participant")
            try:
                instrument, node = key.split("|", 1)
                definition = nodes[node]
                registration = self._registration(node)
                bar_type = OnlyBarType(
                    OnlyInstrumentId.parse(instrument),
                    contract.bar_specification,
                    contract.aggregation_source,
                )
            except (KeyError, ValueError) as exc:
                raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", key) from exc
            if (
                raw["participant_fingerprint"] != self._participant_fingerprint(instrument, node)
                or raw["schema_version"] != registration.checkpoint_schema_version
            ):
                raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "participant identity differs")
            instance = self._instance(instrument, node, definition, bar_type)
            restore = getattr(instance, "restore_checkpoint", None)
            if not callable(restore):
                raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_UNSUPPORTED", node)
            restore(raw["payload"])
        self._last = restored

    def _instance(self, instrument: str, node: str, definition: object, bar_type: OnlyBarType) -> object:
        key = (instrument, node)
        instance = self._instances.get(key)
        if instance is None:
            instance = self._resolver.create(
                definition,  # type: ignore[arg-type]
                _TradingIndicatorRequest(OnlyIndicatorId(f"strategy-{node[:24]}"), bar_type),
            )
            registration = self._registration(node)
            if registration.state_capability is OnlyCalculationStateCapability.CHECKPOINTABLE:
                if (
                    getattr(instance, "checkpoint_schema_version", None) != registration.checkpoint_schema_version
                    or not callable(getattr(instance, "capture_checkpoint", None))
                    or not callable(getattr(instance, "restore_checkpoint", None))
                ):
                    raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_UNSUPPORTED", node)
            self._instances[key] = instance
        return instance

    def _registration(self, node_fingerprint: str) -> OnlyCalculationBackendRegistration:
        node = next(
            (item for item in self._plan.revision.decision_graph.nodes if item.fingerprint == node_fingerprint),
            None,
        )
        if node is None:
            raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", node_fingerprint)
        return self._plan.calculations.resolve(
            node.definition.kind,
            node.definition.type_id,
            node.definition.semantic_version,
            OnlyCalculationBackendKind.TRADING,
        )

    def _participant_fingerprint(self, instrument: str, node_fingerprint: str) -> str:
        binding = next(
            item for item in self._plan.revision.implementation_bindings if item.node_fingerprint == node_fingerprint
        )
        registration = self._registration(node_fingerprint)
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.strategy.checkpoint-participant",
                "schema_version": 1,
                "strategy_fingerprint": str(self._plan.strategy_fingerprint),
                "instrument_id": instrument,
                "node_fingerprint": node_fingerprint,
                "trading_implementation_fingerprint": binding.trading_implementation_fingerprint,
                "checkpoint_schema_version": registration.checkpoint_schema_version,
            }
        )


def _decision_to_checkpoint(decision: OnlyStrategyDecision) -> Mapping[str, object]:
    key = decision.observation_key
    return {
        "strategy_fingerprint": decision.strategy_fingerprint,
        "instrument_id": decision.instrument_id,
        "observation_key": {
            "instrument_id": key.instrument_id,
            "bar_step": key.bar_step,
            "bar_aggregation": key.bar_aggregation,
            "price_type": key.price_type,
            "aggregation_source": key.aggregation_source,
            "adjustment_type": key.adjustment_type,
            "bar_end_ns": key.bar_end_ns,
        },
        "observation_fingerprint": decision.observation_fingerprint,
        "decision_time_ns": decision.decision_time.unix_nanos,
        "eligibility": decision.eligibility,
        "entry": decision.entry,
        "exit": decision.exit,
        "schema_version": decision.schema_version,
    }


def _decision_from_checkpoint(raw: object) -> OnlyStrategyDecision:
    fields = {
        "strategy_fingerprint",
        "instrument_id",
        "observation_key",
        "observation_fingerprint",
        "decision_time_ns",
        "eligibility",
        "entry",
        "exit",
        "schema_version",
    }
    key_fields = {
        "instrument_id",
        "bar_step",
        "bar_aggregation",
        "price_type",
        "aggregation_source",
        "adjustment_type",
        "bar_end_ns",
    }
    if not isinstance(raw, Mapping) or set(raw) != fields:
        raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "invalid decision fields")
    key = raw["observation_key"]
    if not isinstance(key, Mapping) or set(key) != key_fields:
        raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "invalid observation key")
    integer_fields = (key["bar_step"], key["bar_end_ns"], raw["decision_time_ns"], raw["schema_version"])
    if any(not isinstance(value, int) or isinstance(value, bool) for value in integer_fields):
        raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "invalid integer field")
    if any(not isinstance(raw[name], bool) for name in ("eligibility", "entry", "exit")):
        raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "invalid signal field")
    string_values = (
        raw["strategy_fingerprint"],
        raw["instrument_id"],
        raw["observation_fingerprint"],
        key["instrument_id"],
        key["bar_aggregation"],
        key["price_type"],
        key["aggregation_source"],
        key["adjustment_type"],
    )
    if any(not isinstance(value, str) for value in string_values):
        raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", "invalid string field")
    try:
        return OnlyStrategyDecision(
            raw["strategy_fingerprint"],
            raw["instrument_id"],
            OnlyStrategyObservationKey(
                key["instrument_id"],
                key["bar_step"],
                key["bar_aggregation"],
                key["price_type"],
                key["aggregation_source"],
                key["adjustment_type"],
                key["bar_end_ns"],
            ),
            raw["observation_fingerprint"],
            OnlyTimestamp.from_unix_nanos(raw["decision_time_ns"]),
            raw["eligibility"],
            raw["entry"],
            raw["exit"],
            raw["schema_version"],
        )
    except (TypeError, ValueError) as exc:
        raise OnlyStrategyResolutionError("STRATEGY_CHECKPOINT_CORRUPT", type(exc).__name__) from exc


def only_strategy_observation_key(bar: OnlyBar) -> OnlyStrategyObservationKey:
    specification = bar.bar_type.specification
    return OnlyStrategyObservationKey(
        str(bar.instrument_id),
        specification.step,
        specification.aggregation.value,
        specification.price_type.value,
        bar.bar_type.aggregation_source.value,
        bar.adjustment_type.value,
        OnlyTimestamp.from_datetime(bar.bar_end).unix_nanos,
    )


def only_strategy_observation_fingerprint(bar: OnlyBar) -> str:
    """Hash exact finalized BAR semantics while excluding transport/init metadata."""

    specification = bar.bar_type.specification
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.strategy.observation.bar",
            "schema_version": 1,
            "instrument_id": str(bar.instrument_id),
            "bar_specification": {
                "step": specification.step,
                "aggregation": specification.aggregation.value,
                "price_type": specification.price_type.value,
            },
            "aggregation_source": bar.bar_type.aggregation_source.value,
            "bar_start": bar.bar_start,
            "bar_end": bar.bar_end,
            "ts_event": bar.ts_event,
            "open": bar.open.value,
            "high": bar.high.value,
            "low": bar.low.value,
            "close": bar.close.value,
            "price_precision": bar.close.precision,
            "volume": bar.volume.value,
            "volume_precision": bar.volume.precision,
            "quote_volume": None if bar.quote_volume is None else bar.quote_volume.value,
            "turnover": None if bar.turnover is None else bar.turnover.amount,
            "trade_count": bar.trade_count,
            "open_interest": None if bar.open_interest is None else bar.open_interest.value,
            "revision": bar.revision,
            "adjustment_type": bar.adjustment_type.value,
            "trading_day": bar.trading_day,
            "session_type": bar.session_type.value,
        }
    )


def _decision(outputs: Mapping[tuple[str, str], object], binding: OnlyStrategySignalBinding) -> bool:
    value = outputs[(binding.node_fingerprint, binding.output_name)]
    if value is None:
        return False
    if not isinstance(value, bool):
        raise OnlyStrategyResolutionError("TRADING_BACKEND_OUTPUT_INVALID", "Strategy decision is not Boolean")
    return value


def _bar_source(bar: OnlyBar, source: str | None) -> object:
    values: dict[str, object] = {
        "bar.open": bar.open.value,
        "bar.high": bar.high.value,
        "bar.low": bar.low.value,
        "bar.close": bar.close.value,
        "bar.volume": bar.volume.value,
        "bar.quote_volume": None if bar.quote_volume is None else bar.quote_volume.value,
        "bar.turnover": None if bar.turnover is None else bar.turnover.amount,
        "bar.trade_count": bar.trade_count,
        "bar.open_interest": None if bar.open_interest is None else bar.open_interest.value,
    }
    try:
        return values[str(source)]
    except KeyError as exc:
        raise OnlyStrategyResolutionError("STRATEGY_OBSERVATION_NOT_ADMITTED", f"unsupported source {source}") from exc


def only_invoke_trading_calculation(
    instance: object,
    outputs: tuple[OnlyOutputDefinition, ...],
    bar: OnlyBar,
    inputs: Mapping[str, object],
) -> Mapping[str, object]:
    """Shared exact TRADING invocation used by Runtime and Certification Authority."""

    if isinstance(instance, OnlyBarIndicator):
        instance.update_bar(bar)
        snapshot = instance.snapshot()
        result: dict[str, object] = {}
        for output in outputs:
            name = str(output.name)
            value = getattr(snapshot, name)
            if isinstance(value, Enum):
                value = value.value
            result[name] = value
        return result
    update = getattr(instance, "update", None)
    if not callable(update):
        raise OnlyStrategyResolutionError("TRADING_BACKEND_INVALID", type(instance).__name__)
    value = update(MappingProxyType(dict(inputs)))
    if not isinstance(value, Mapping):
        raise OnlyStrategyResolutionError("TRADING_BACKEND_OUTPUT_INVALID", type(instance).__name__)
    return value


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
