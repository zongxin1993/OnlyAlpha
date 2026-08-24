"""Immutable Strategy Revision semantic core and its sole authoritative identity."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyAggregationSource
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSpecification

STRATEGY_REVISION_SCHEMA_VERSION = 1


class OnlyStrategyUniverseKind(StrEnum):
    SINGLE_INSTRUMENT = "SINGLE_INSTRUMENT"
    EXPLICIT_INSTRUMENT_SET = "EXPLICIT_INSTRUMENT_SET"


class OnlyStrategyDataKind(StrEnum):
    BAR = "BAR"


class OnlyStrategyObservationAdmission(StrEnum):
    FINAL_ONLY = "FINAL_ONLY"


class OnlyStrategyMissingDecisionPolicy(StrEnum):
    FALSE = "FALSE"


@dataclass(frozen=True, slots=True)
class OnlyStrategyFingerprint:
    value: str

    def __post_init__(self) -> None:
        _sha(self.value, "strategy_fingerprint")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyStrategyUniverse:
    instruments: tuple[OnlyInstrumentId, ...]
    kind: OnlyStrategyUniverseKind | None = None

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.instruments, key=str))
        if not canonical or len(canonical) != len(set(canonical)):
            raise ValueError("Strategy Universe instruments must be non-empty and unique")
        expected = (
            OnlyStrategyUniverseKind.SINGLE_INSTRUMENT
            if len(canonical) == 1
            else OnlyStrategyUniverseKind.EXPLICIT_INSTRUMENT_SET
        )
        if self.kind is not None and self.kind is not expected:
            raise ValueError("Strategy Universe kind conflicts with exact membership")
        object.__setattr__(self, "instruments", canonical)
        object.__setattr__(self, "kind", expected)

    def to_dict(self) -> dict[str, object]:
        assert self.kind is not None
        return {"kind": self.kind.value, "instruments": [str(item) for item in self.instruments]}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyStrategyUniverse:
        _exact(payload, {"kind", "instruments"}, "Strategy Universe")
        values = payload["instruments"]
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise ValueError("Strategy Universe instruments must be an array of strings")
        kind = payload["kind"]
        if not isinstance(kind, str):
            raise ValueError("Strategy Universe kind must be a string")
        return cls(tuple(OnlyInstrumentId.parse(item) for item in values), OnlyStrategyUniverseKind(kind))


@dataclass(frozen=True, slots=True)
class OnlyStrategyMarketInputContract:
    bar_specification: OnlyBarSpecification
    aggregation_source: OnlyAggregationSource
    adjustment_type: OnlyAdjustmentType
    adjustment_reference: str | None = None
    data_kind: OnlyStrategyDataKind = OnlyStrategyDataKind.BAR
    observation_admission: OnlyStrategyObservationAdmission = OnlyStrategyObservationAdmission.FINAL_ONLY
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Strategy Market Input Contract schema")
        if self.data_kind is not OnlyStrategyDataKind.BAR:
            raise ValueError("Strategy Market Input V1 supports BAR only")
        if self.observation_admission is not OnlyStrategyObservationAdmission.FINAL_ONLY:
            raise ValueError("Strategy Market Input V1 admits FINAL bars only")
        if self.adjustment_type is OnlyAdjustmentType.RAW and self.adjustment_reference is not None:
            raise ValueError("RAW Strategy input cannot declare an adjustment reference")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "data_kind": self.data_kind.value,
            "bar_specification": {
                "step": self.bar_specification.step,
                "aggregation": self.bar_specification.aggregation.value,
                "price_type": self.bar_specification.price_type.value,
            },
            "aggregation_source": self.aggregation_source.value,
            "adjustment_type": self.adjustment_type.value,
            "adjustment_reference": self.adjustment_reference,
            "observation_admission": self.observation_admission.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyStrategyMarketInputContract:
        from onlyalpha.domain.enums import OnlyBarAggregation, OnlyPriceType

        _exact(
            payload,
            {
                "schema_version",
                "data_kind",
                "bar_specification",
                "aggregation_source",
                "adjustment_type",
                "adjustment_reference",
                "observation_admission",
            },
            "Strategy Market Input Contract",
        )
        bar = _mapping(payload["bar_specification"], "Strategy bar specification")
        _exact(bar, {"step", "aggregation", "price_type"}, "Strategy bar specification")
        step = bar["step"]
        if isinstance(step, bool) or not isinstance(step, int):
            raise ValueError("Strategy bar step must be an integer")
        adjustment_reference = payload["adjustment_reference"]
        if adjustment_reference is not None and not isinstance(adjustment_reference, str):
            raise ValueError("Strategy adjustment reference must be a string or null")
        return cls(
            OnlyBarSpecification(
                step, OnlyBarAggregation(_string(bar, "aggregation")), OnlyPriceType(_string(bar, "price_type"))
            ),
            OnlyAggregationSource(_string(payload, "aggregation_source")),
            OnlyAdjustmentType(_string(payload, "adjustment_type")),
            adjustment_reference,
            OnlyStrategyDataKind(_string(payload, "data_kind")),
            OnlyStrategyObservationAdmission(_string(payload, "observation_admission")),
            _integer(payload, "schema_version"),
        )


@dataclass(frozen=True, order=True, slots=True)
class OnlyStrategySignalBinding:
    node_fingerprint: str
    output_name: str

    def __post_init__(self) -> None:
        _sha(self.node_fingerprint, "Strategy Signal node identity")
        if not self.output_name.strip():
            raise ValueError("Strategy Signal output name is required")

    def to_dict(self) -> dict[str, str]:
        return {"node_fingerprint": self.node_fingerprint, "output_name": self.output_name}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyStrategySignalBinding:
        _exact(payload, {"node_fingerprint", "output_name"}, "Strategy Signal binding")
        return cls(_string(payload, "node_fingerprint"), _string(payload, "output_name"))


@dataclass(frozen=True, slots=True)
class OnlyStrategySignalSemantics:
    eligibility: OnlyStrategySignalBinding
    entry: OnlyStrategySignalBinding
    exit: OnlyStrategySignalBinding
    missing_decision: OnlyStrategyMissingDecisionPolicy = OnlyStrategyMissingDecisionPolicy.FALSE
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.missing_decision is not OnlyStrategyMissingDecisionPolicy.FALSE:
            raise ValueError("unsupported Strategy Signal semantics")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "eligibility": self.eligibility.to_dict(),
            "entry": self.entry.to_dict(),
            "exit": self.exit.to_dict(),
            "missing_decision": self.missing_decision.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyStrategySignalSemantics:
        _exact(payload, {"schema_version", "eligibility", "entry", "exit", "missing_decision"}, "Signal semantics")
        return cls(
            OnlyStrategySignalBinding.from_dict(_mapping(payload["eligibility"], "eligibility binding")),
            OnlyStrategySignalBinding.from_dict(_mapping(payload["entry"], "entry binding")),
            OnlyStrategySignalBinding.from_dict(_mapping(payload["exit"], "exit binding")),
            OnlyStrategyMissingDecisionPolicy(_string(payload, "missing_decision")),
            _integer(payload, "schema_version"),
        )


@dataclass(frozen=True, order=True, slots=True)
class OnlyStrategyImplementationBinding:
    node_fingerprint: str
    research_implementation_fingerprint: str
    trading_implementation_fingerprint: str

    def __post_init__(self) -> None:
        _sha(self.node_fingerprint, "Calculation semantic identity")
        _sha(self.research_implementation_fingerprint, "Research implementation identity")
        _sha(self.trading_implementation_fingerprint, "Trading implementation identity")

    def to_dict(self) -> dict[str, str]:
        return {
            "node_fingerprint": self.node_fingerprint,
            "research_implementation_fingerprint": self.research_implementation_fingerprint,
            "trading_implementation_fingerprint": self.trading_implementation_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyStrategyImplementationBinding:
        _exact(
            payload,
            {
                "node_fingerprint",
                "research_implementation_fingerprint",
                "trading_implementation_fingerprint",
            },
            "Strategy implementation binding",
        )
        return cls(
            _string(payload, "node_fingerprint"),
            _string(payload, "research_implementation_fingerprint"),
            _string(payload, "trading_implementation_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class OnlyStrategyRevision:
    universe: OnlyStrategyUniverse
    market_input_contract: OnlyStrategyMarketInputContract
    decision_graph: OnlyCalculationGraphDefinition
    implementation_bindings: tuple[OnlyStrategyImplementationBinding, ...]
    signal_semantics: OnlyStrategySignalSemantics
    schema_version: int = STRATEGY_REVISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != STRATEGY_REVISION_SCHEMA_VERSION:
            raise ValueError("unsupported Strategy Revision schema")
        # A Revision is an immutable canonical value, not merely an object that
        # happens to hash canonically.  Normalize the graph to its stable
        # dependency order so commit/load and independent construction produce
        # the same value as well as the same fingerprint.
        ordered_graph = OnlyCalculationGraphDefinition(
            self.decision_graph.ordered_nodes,
            self.decision_graph.schema_version,
        )
        object.__setattr__(self, "decision_graph", ordered_graph)
        canonical = tuple(sorted(self.implementation_bindings))
        if canonical != self.implementation_bindings or len(canonical) != len(set(canonical)):
            raise ValueError("Strategy implementation bindings must be canonical and unique")
        graph_nodes = {item.fingerprint for item in self.decision_graph.nodes}
        if {item.node_fingerprint for item in canonical} != graph_nodes:
            raise ValueError("Strategy implementation bindings must exactly cover the Decision Graph")
        for binding, semantic_type in (
            (self.signal_semantics.eligibility, "ELIGIBILITY"),
            (self.signal_semantics.entry, "ENTRY_SIGNAL"),
            (self.signal_semantics.exit, "EXIT_SIGNAL"),
        ):
            node = next(
                (item for item in self.decision_graph.nodes if item.fingerprint == binding.node_fingerprint), None
            )
            output = (
                None
                if node is None
                else next((item for item in node.definition.outputs if item.name == binding.output_name), None)
            )
            if output is None or output.semantic_type != semantic_type or output.data_type.value != "BOOLEAN":
                raise ValueError("Strategy Signal binding does not resolve in the Decision Graph")

    @property
    def strategy_fingerprint(self) -> OnlyStrategyFingerprint:
        return OnlyStrategyFingerprint(only_strategy_revision_fingerprint(self))

    def semantic_payload(self) -> Mapping[str, object]:
        payload = only_canonical_payload(
            {
                "domain": "onlyalpha.strategy.revision",
                "schema_version": self.schema_version,
                "universe": self.universe.to_dict(),
                "market_input_contract": self.market_input_contract.to_dict(),
                "decision_graph_fingerprint": self.decision_graph.fingerprint,
                "implementation_bindings": [item.to_dict() for item in self.implementation_bindings],
                "signal_semantics": self.signal_semantics.to_dict(),
            }
        )
        if not isinstance(payload, Mapping):
            raise TypeError("Strategy Revision semantic payload must be an object")
        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "strategy_fingerprint": str(self.strategy_fingerprint),
            "universe": self.universe.to_dict(),
            "market_input_contract": self.market_input_contract.to_dict(),
            "decision_graph_fingerprint": self.decision_graph.fingerprint,
            "decision_graph": self.decision_graph.to_dict(),
            "implementation_bindings": [item.to_dict() for item in self.implementation_bindings],
            "signal_semantics": self.signal_semantics.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyStrategyRevision:
        _exact(
            payload,
            {
                "schema_version",
                "strategy_fingerprint",
                "universe",
                "market_input_contract",
                "decision_graph_fingerprint",
                "decision_graph",
                "implementation_bindings",
                "signal_semantics",
            },
            "Strategy Revision",
        )
        raw_bindings = payload["implementation_bindings"]
        if not isinstance(raw_bindings, list):
            raise ValueError("Strategy implementation bindings must be an array")
        result = cls(
            OnlyStrategyUniverse.from_dict(_mapping(payload["universe"], "Strategy Universe")),
            OnlyStrategyMarketInputContract.from_dict(_mapping(payload["market_input_contract"], "Market Input")),
            OnlyCalculationGraphDefinition.from_dict(_mapping(payload["decision_graph"], "Decision Graph")),
            tuple(
                OnlyStrategyImplementationBinding.from_dict(_mapping(item, "implementation binding"))
                for item in raw_bindings
            ),
            OnlyStrategySignalSemantics.from_dict(_mapping(payload["signal_semantics"], "Signal semantics")),
            _integer(payload, "schema_version"),
        )
        if _string(payload, "decision_graph_fingerprint") != result.decision_graph.fingerprint:
            raise ValueError("Strategy Decision Graph fingerprint mismatch")
        if _string(payload, "strategy_fingerprint") != str(result.strategy_fingerprint):
            raise ValueError("Strategy fingerprint mismatch")
        return result


def only_strategy_revision_fingerprint(revision: OnlyStrategyRevision) -> str:
    """The one public authoritative Strategy identity constructor."""

    if not isinstance(revision, OnlyStrategyRevision):
        raise TypeError("Strategy fingerprint requires an OnlyStrategyRevision")
    return only_canonical_fingerprint(revision.semantic_payload())


def _sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


def _exact(payload: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{context} fields are invalid")


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return value


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "STRATEGY_"))]
