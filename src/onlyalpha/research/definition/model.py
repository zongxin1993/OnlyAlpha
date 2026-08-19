"""Authoring-channel-neutral Research Definition V1 contract."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from onlyalpha.calculation import (
    OnlyCalculationScalar,
    OnlyCalculationTypeReference,
    only_calculation_scalar_from_dict,
    only_calculation_scalar_sort_key,
    only_calculation_scalar_to_dict,
)
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.market import OnlyBarSpecification
from onlyalpha.research.dataset import OnlyResearchDatasetDefinition
from onlyalpha.research.evaluation.definition import OnlyResearchStatisticsDefinition

from .expression import (
    OnlyResearchBooleanExpression,
    OnlyResearchVariableRef,
    only_canonicalize_research_expression,
    only_research_expression_from_dict,
)

RESEARCH_DEFINITION_SCHEMA_VERSION = 1


class OnlyResearchUniverseKind(StrEnum):
    SINGLE_INSTRUMENT = "SINGLE_INSTRUMENT"
    EXPLICIT_INSTRUMENT_SET = "EXPLICIT_INSTRUMENT_SET"
    REGISTERED_POOL = "REGISTERED_POOL"
    REGISTERED_UNIVERSE = "REGISTERED_UNIVERSE"


@dataclass(frozen=True, slots=True)
class OnlyResearchUniverseSelection:
    kind: OnlyResearchUniverseKind
    instrument_ids: tuple[str, ...] = ()
    registered_id: str | None = None

    def __post_init__(self) -> None:
        explicit = self.kind in {
            OnlyResearchUniverseKind.SINGLE_INSTRUMENT,
            OnlyResearchUniverseKind.EXPLICIT_INSTRUMENT_SET,
        }
        if explicit:
            expected = 1 if self.kind is OnlyResearchUniverseKind.SINGLE_INSTRUMENT else None
            canonical = tuple(sorted(self.instrument_ids))
            if (
                not canonical
                or len(canonical) != len(set(canonical))
                or (expected is not None and len(canonical) != expected)
            ):
                raise ValueError("explicit Universe instruments are invalid")
            if self.registered_id is not None:
                raise ValueError("explicit Universe cannot have registered_id")
            object.__setattr__(self, "instrument_ids", canonical)
        else:
            if self.instrument_ids or not self.registered_id or any(char.isspace() for char in self.registered_id):
                raise ValueError("registered Universe identity is invalid")

    def to_dict(self) -> Mapping[str, object]:
        return {
            "kind": self.kind.value,
            "instrument_ids": list(self.instrument_ids),
            "registered_id": self.registered_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchUniverseSelection:
        _exact(payload, {"kind", "instrument_ids", "registered_id"}, "Universe")
        values = payload["instrument_ids"]
        registered = payload["registered_id"]
        if (
            not isinstance(values, list)
            or any(not isinstance(item, str) for item in values)
            or (registered is not None and not isinstance(registered, str))
        ):
            raise ValueError("Universe fields are invalid")
        return cls(OnlyResearchUniverseKind(_string(payload["kind"])), tuple(values), registered)


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetSelection:
    universe: OnlyResearchUniverseSelection
    bar_specification: OnlyBarSpecification
    aggregation_source: OnlyAggregationSource
    start: str
    end: str
    adjustment_type: OnlyAdjustmentType = OnlyAdjustmentType.RAW
    adjustment_reference: str | None = None

    def __post_init__(self) -> None:
        # Exact UTC/time-range admission remains owned by the existing Dataset Definition.
        self.to_dataset_definition(self.universe.instrument_ids or ("PLACEHOLDER.PLACEHOLDER",))

    def to_dataset_definition(self, instrument_ids: tuple[str, ...]) -> OnlyResearchDatasetDefinition:
        from datetime import datetime

        from onlyalpha.core.ranges import OnlyTimeRange
        from onlyalpha.domain.identifiers import OnlyInstrumentId

        return OnlyResearchDatasetDefinition(
            tuple(OnlyInstrumentId.parse(item) for item in instrument_ids),
            self.bar_specification,
            self.aggregation_source,
            OnlyTimeRange(datetime.fromisoformat(self.start), datetime.fromisoformat(self.end)),
            self.adjustment_type,
            self.adjustment_reference,
        )

    def to_dict(self) -> Mapping[str, object]:
        return {
            "universe": self.universe.to_dict(),
            "bar_specification": {
                "step": self.bar_specification.step,
                "aggregation": self.bar_specification.aggregation.value,
                "price_type": self.bar_specification.price_type.value,
            },
            "aggregation_source": self.aggregation_source.value,
            "start": self.start,
            "end": self.end,
            "adjustment_type": self.adjustment_type.value,
            "adjustment_reference": self.adjustment_reference,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchDatasetSelection:
        _exact(
            payload,
            {
                "universe",
                "bar_specification",
                "aggregation_source",
                "start",
                "end",
                "adjustment_type",
                "adjustment_reference",
            },
            "Dataset selection",
        )
        bar = _mapping(payload["bar_specification"])
        _exact(bar, {"step", "aggregation", "price_type"}, "bar specification")
        step = bar["step"]
        if isinstance(step, bool) or not isinstance(step, int):
            raise ValueError("bar step must be an integer")
        adjustment_reference = payload["adjustment_reference"]
        if adjustment_reference is not None and not isinstance(adjustment_reference, str):
            raise ValueError("adjustment_reference must be a string or null")
        return cls(
            OnlyResearchUniverseSelection.from_dict(_mapping(payload["universe"])),
            OnlyBarSpecification(
                step, OnlyBarAggregation(_string(bar["aggregation"])), OnlyPriceType(_string(bar["price_type"]))
            ),
            OnlyAggregationSource(_string(payload["aggregation_source"])),
            _string(payload["start"]),
            _string(payload["end"]),
            OnlyAdjustmentType(_string(payload["adjustment_type"])),
            adjustment_reference,
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchFixedParameter:
    value: OnlyCalculationScalar

    def __post_init__(self) -> None:
        _scalar(self.value, "Fixed parameter")

    def to_dict(self) -> Mapping[str, object]:
        return {"kind": "FIXED", "value": only_calculation_scalar_to_dict(self.value)}


@dataclass(frozen=True, slots=True)
class OnlyResearchSweepParameter:
    values: tuple[OnlyCalculationScalar, ...]

    def __post_init__(self) -> None:
        if len(self.values) < 2:
            raise ValueError("Sweep requires at least two values")
        for item in self.values:
            _scalar(item, "Sweep parameter")
        if len({(type(item), item) for item in self.values}) != len(self.values):
            raise ValueError("Sweep contains duplicate values")
        object.__setattr__(self, "values", tuple(sorted(self.values, key=only_calculation_scalar_sort_key)))

    def to_dict(self) -> Mapping[str, object]:
        return {"kind": "SWEEP", "values": [only_calculation_scalar_to_dict(item) for item in self.values]}


type OnlyResearchParameterBinding = OnlyResearchFixedParameter | OnlyResearchSweepParameter


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchCalculationInput:
    input_name: str
    source: str | OnlyResearchVariableRef

    def to_dict(self) -> Mapping[str, object]:
        return {
            "input_name": self.input_name,
            "source": self.source if isinstance(self.source, str) else self.source.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationInstance:
    instance_key: str
    type_reference: OnlyCalculationTypeReference
    parameters: Mapping[str, OnlyResearchParameterBinding]
    published_outputs: tuple[str, ...]
    input_bindings: tuple[OnlyResearchCalculationInput, ...] = ()
    primary_output: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.instance_key, "instance_key")
        outputs = tuple(sorted(self.published_outputs))
        if not outputs or len(outputs) != len(set(outputs)):
            raise ValueError("published_outputs must be non-empty and unique")
        if self.primary_output is not None and self.primary_output not in outputs:
            raise ValueError("primary_output must be published")
        if len(self.input_bindings) != len({item.input_name for item in self.input_bindings}):
            raise ValueError("Calculation input bindings are duplicated")
        object.__setattr__(self, "parameters", MappingProxyType(dict(sorted(self.parameters.items()))))
        object.__setattr__(self, "published_outputs", outputs)
        object.__setattr__(self, "input_bindings", tuple(sorted(self.input_bindings)))

    def to_dict(self) -> Mapping[str, object]:
        return {
            "instance_key": self.instance_key,
            "type_reference": self.type_reference.to_dict(),
            "parameters": {name: value.to_dict() for name, value in self.parameters.items()},
            "published_outputs": list(self.published_outputs),
            "input_bindings": [item.to_dict() for item in self.input_bindings],
            "primary_output": self.primary_output,
        }

    def semantic_dict(self) -> Mapping[str, object]:
        result = dict(self.to_dict())
        result.pop("primary_output")
        return result


@dataclass(frozen=True, slots=True)
class OnlyResearchSignals:
    entry: OnlyResearchBooleanExpression | None = None
    exit: OnlyResearchBooleanExpression | None = None

    def __post_init__(self) -> None:
        if self.entry is not None:
            object.__setattr__(self, "entry", only_canonicalize_research_expression(self.entry))
        if self.exit is not None:
            object.__setattr__(self, "exit", only_canonicalize_research_expression(self.exit))

    def to_dict(self) -> Mapping[str, object]:
        return {
            "entry": None if self.entry is None else self.entry.to_dict(),
            "exit": None if self.exit is None else self.exit.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsRequest:
    variable: OnlyResearchVariableRef
    target_instance_key: str
    definition: OnlyResearchStatisticsDefinition

    def to_dict(self) -> Mapping[str, object]:
        return {
            "variable": self.variable.to_dict(),
            "target_instance_key": self.target_instance_key,
            "definition": self.definition.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchDefinition:
    dataset: OnlyResearchDatasetSelection
    calculations: tuple[OnlyResearchCalculationInstance, ...]
    eligibility: OnlyResearchBooleanExpression | None
    signals: OnlyResearchSignals
    targets: tuple[OnlyResearchCalculationInstance, ...]
    statistics: tuple[OnlyResearchStatisticsRequest, ...]
    schema_version: int = RESEARCH_DEFINITION_SCHEMA_VERSION
    display_metadata: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != RESEARCH_DEFINITION_SCHEMA_VERSION:
            raise ValueError(f"unsupported Research Definition schema version: {self.schema_version}")
        if not self.calculations or not self.targets or not self.statistics:
            raise ValueError("Research Definition requires calculations, targets and statistics")
        keys = tuple(item.instance_key for item in (*self.calculations, *self.targets))
        if len(keys) != len(set(keys)):
            raise ValueError("Research Definition contains duplicate instance_key")
        if self.eligibility is not None:
            object.__setattr__(self, "eligibility", only_canonicalize_research_expression(self.eligibility))
        object.__setattr__(self, "calculations", tuple(sorted(self.calculations, key=lambda item: item.instance_key)))
        object.__setattr__(self, "targets", tuple(sorted(self.targets, key=lambda item: item.instance_key)))
        object.__setattr__(self, "statistics", tuple(sorted(self.statistics, key=lambda item: str(item.to_dict()))))
        object.__setattr__(self, "display_metadata", MappingProxyType(dict(self.display_metadata)))

    def semantic_payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "dataset": self.dataset.to_dict(),
            "calculations": [item.semantic_dict() for item in self.calculations],
            "eligibility": None if self.eligibility is None else self.eligibility.to_dict(),
            "signals": self.signals.to_dict(),
            "targets": [item.semantic_dict() for item in self.targets],
            "statistics": [item.to_dict() for item in self.statistics],
        }

    @property
    def definition_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.semantic_payload())

    def to_dict(self) -> Mapping[str, object]:
        payload = dict(self.semantic_payload())
        payload["calculations"] = [item.to_dict() for item in self.calculations]
        payload["targets"] = [item.to_dict() for item in self.targets]
        payload["display_metadata"] = self.display_metadata
        return cast(
            Mapping[str, object],
            only_canonical_payload(payload),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchDefinition:
        _exact(
            payload,
            {
                "schema_version",
                "dataset",
                "calculations",
                "eligibility",
                "signals",
                "targets",
                "statistics",
                "display_metadata",
            },
            "Research Definition",
        )
        calculations = _array(payload["calculations"], "calculations")
        targets = _array(payload["targets"], "targets")
        statistics = _array(payload["statistics"], "statistics")
        signals = _mapping(payload["signals"])
        _exact(signals, {"entry", "exit"}, "signals")
        version = payload["schema_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("schema_version must be an integer")
        return cls(
            OnlyResearchDatasetSelection.from_dict(_mapping(payload["dataset"])),
            tuple(_calculation(_mapping(item)) for item in calculations),
            None
            if payload["eligibility"] is None
            else only_research_expression_from_dict(_mapping(payload["eligibility"])),
            OnlyResearchSignals(
                None if signals["entry"] is None else only_research_expression_from_dict(_mapping(signals["entry"])),
                None if signals["exit"] is None else only_research_expression_from_dict(_mapping(signals["exit"])),
            ),
            tuple(_calculation(_mapping(item)) for item in targets),
            tuple(_statistics(_mapping(item)) for item in statistics),
            version,
            _mapping(payload["display_metadata"]),
        )


def _calculation(payload: Mapping[str, object]) -> OnlyResearchCalculationInstance:
    _exact(
        payload,
        {"instance_key", "type_reference", "parameters", "published_outputs", "input_bindings", "primary_output"},
        "Calculation instance",
    )
    parameters = _mapping(payload["parameters"])
    outputs = _array(payload["published_outputs"], "published_outputs")
    inputs = _array(payload["input_bindings"], "input_bindings")
    primary = payload["primary_output"]
    if any(not isinstance(item, str) for item in outputs) or (primary is not None and not isinstance(primary, str)):
        raise ValueError("Calculation outputs are invalid")
    return OnlyResearchCalculationInstance(
        _string(payload["instance_key"]),
        OnlyCalculationTypeReference.from_dict(_mapping(payload["type_reference"])),
        {name: _parameter(_mapping(item)) for name, item in parameters.items()},
        tuple(cast(str, item) for item in outputs),
        tuple(_input(_mapping(item)) for item in inputs),
        primary,
    )


def _parameter(payload: Mapping[str, object]) -> OnlyResearchParameterBinding:
    kind = payload.get("kind")
    if kind == "FIXED":
        _exact(payload, {"kind", "value"}, "Fixed parameter")
        return OnlyResearchFixedParameter(only_calculation_scalar_from_dict(payload["value"], "Fixed parameter"))
    if kind == "SWEEP":
        _exact(payload, {"kind", "values"}, "Sweep parameter")
        return OnlyResearchSweepParameter(
            tuple(
                only_calculation_scalar_from_dict(item, "Sweep parameter")
                for item in _array(payload["values"], "Sweep values")
            )
        )
    raise ValueError("unknown parameter binding kind")


def _input(payload: Mapping[str, object]) -> OnlyResearchCalculationInput:
    _exact(payload, {"input_name", "source"}, "Calculation input")
    source = payload["source"]
    if isinstance(source, str):
        return OnlyResearchCalculationInput(_string(payload["input_name"]), source)
    ref = _mapping(source)
    _exact(ref, {"kind", "instance_key", "output_name"}, "variable source")
    if ref["kind"] != "VARIABLE":
        raise ValueError("Calculation input source must be a variable")
    return OnlyResearchCalculationInput(
        _string(payload["input_name"]),
        OnlyResearchVariableRef(_string(ref["instance_key"]), _string(ref["output_name"])),
    )


def _statistics(payload: Mapping[str, object]) -> OnlyResearchStatisticsRequest:
    _exact(payload, {"variable", "target_instance_key", "definition"}, "Statistics request")
    variable = _mapping(payload["variable"])
    _exact(variable, {"kind", "instance_key", "output_name"}, "Statistics variable")
    return OnlyResearchStatisticsRequest(
        OnlyResearchVariableRef(_string(variable["instance_key"]), _string(variable["output_name"])),
        _string(payload["target_instance_key"]),
        OnlyResearchStatisticsDefinition.from_dict(_mapping(payload["definition"])),
    )


def _identifier(value: str, context: str) -> None:
    if re.fullmatch(r"[a-z][a-z0-9_]*", value) is None:
        raise ValueError(f"{context} must be a lower snake-case identifier")


def _scalar(value: object, context: str) -> None:
    if (
        value is None
        or isinstance(value, (str, bool, Decimal))
        or (isinstance(value, int) and not isinstance(value, bool))
    ):
        return
    raise ValueError(f"{context} must use a type-preserving Calculation scalar")


def _exact(payload: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(payload) != expected:
        raise ValueError(
            f"{context} fields are invalid; missing={sorted(expected - set(payload))}, unknown={sorted(set(payload) - expected)}"
        )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("value must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    return value


__all__ = [name for name in globals() if name.startswith(("Only", "RESEARCH_DEFINITION_"))]
