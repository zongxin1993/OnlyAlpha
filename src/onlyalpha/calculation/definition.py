"""Runtime-independent canonical calculation definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload

OnlyCalculationScalar = str | int | bool | Decimal | None


class OnlyCalculationKind(StrEnum):
    INDICATOR = "INDICATOR"
    FACTOR = "FACTOR"


class OnlyCalculationBackendKind(StrEnum):
    TRADING = "TRADING"
    RESEARCH = "RESEARCH"


class OnlyCalculationDataType(StrEnum):
    DECIMAL = "DECIMAL"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    STRING = "STRING"


class OnlyFactorKind(StrEnum):
    TIME_SERIES = "TIME_SERIES"
    CROSS_SECTION = "CROSS_SECTION"


class OnlyMissingValuePolicy(StrEnum):
    FAIL = "FAIL"
    SKIP = "SKIP"
    PROPAGATE = "PROPAGATE"
    RESET = "RESET"


class OnlyTimestampSemantic(StrEnum):
    BAR_OPEN = "BAR_OPEN"
    BAR_CLOSE = "BAR_CLOSE"
    EVENT_TIME = "EVENT_TIME"
    OBSERVATION_TIME = "OBSERVATION_TIME"
    AVAILABILITY_TIME = "AVAILABILITY_TIME"


class OnlyPreReadyOutput(StrEnum):
    NULL = "NULL"
    PARTIAL = "PARTIAL"


class OnlyParameterType(StrEnum):
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    STRING = "STRING"
    BOOLEAN = "BOOLEAN"


@dataclass(frozen=True, slots=True)
class OnlyParameterDefinition:
    name: str
    parameter_type: OnlyParameterType
    required: bool = True
    default: OnlyCalculationScalar = None
    minimum: Decimal | int | None = None
    maximum: Decimal | int | None = None
    enum_values: tuple[OnlyCalculationScalar, ...] = ()
    uppercase: bool = False

    def __post_init__(self) -> None:
        if not self.name or any(char.isspace() for char in self.name):
            raise ValueError("parameter name must be non-empty and contain no whitespace")
        if not self.required and self.default is None:
            raise ValueError(f"optional parameter {self.name} requires an explicit default")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"parameter {self.name} has an invalid range")

    def normalize(self, value: object) -> OnlyCalculationScalar:
        if self.parameter_type is OnlyParameterType.INTEGER:
            if isinstance(value, bool):
                raise ValueError(f"parameter {self.name} must be INTEGER")
            normalized: OnlyCalculationScalar = int(str(value))
        elif self.parameter_type is OnlyParameterType.DECIMAL:
            normalized = Decimal(str(value))
            if not normalized.is_finite():
                raise ValueError(f"parameter {self.name} must be finite")
        elif self.parameter_type is OnlyParameterType.STRING:
            normalized = str(value).upper() if self.uppercase else str(value)
        elif self.parameter_type is OnlyParameterType.BOOLEAN:
            if not isinstance(value, bool):
                raise ValueError(f"parameter {self.name} must be BOOLEAN")
            normalized = value
        else:  # pragma: no cover - enum is closed
            raise ValueError(f"unsupported parameter type: {self.parameter_type}")
        if self.minimum is not None and normalized < self.minimum:  # type: ignore[operator]
            raise ValueError(f"parameter {self.name} is below its minimum")
        if self.maximum is not None and normalized > self.maximum:  # type: ignore[operator]
            raise ValueError(f"parameter {self.name} is above its maximum")
        if self.enum_values and normalized not in self.enum_values:
            raise ValueError(f"parameter {self.name} is not an allowed value")
        return normalized


@dataclass(frozen=True, slots=True)
class OnlyParameterSchema:
    fields: tuple[OnlyParameterDefinition, ...] = ()

    def __post_init__(self) -> None:
        names = tuple(item.name for item in self.fields)
        if len(names) != len(set(names)):
            raise ValueError("parameter schema contains duplicate fields")

    def normalize(self, values: Mapping[str, object]) -> Mapping[str, OnlyCalculationScalar]:
        known = {item.name: item for item in self.fields}
        unknown = set(values) - set(known)
        if unknown:
            raise ValueError(f"unknown calculation parameters: {sorted(unknown)}")
        result: dict[str, OnlyCalculationScalar] = {}
        for name in sorted(known):
            spec = known[name]
            if name in values:
                result[name] = spec.normalize(values[name])
            elif spec.required:
                raise ValueError(f"required calculation parameter is missing: {name}")
            else:
                result[name] = spec.normalize(spec.default)
        return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class OnlyInputDefinition:
    name: str
    data_type: OnlyCalculationDataType
    nullable: bool = False
    dimensions: tuple[str, ...] = ("TIME",)
    semantic_type: str = "NUMERIC_SERIES"
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyOutputDefinition:
    name: str
    data_type: OnlyCalculationDataType
    nullable: bool
    dimensions: tuple[str, ...] = ("TIME",)
    semantic_type: str = "NUMERIC_SERIES"
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyWarmupDefinition:
    minimum_observations: int
    ready_condition: str
    pre_ready_output: OnlyPreReadyOutput
    initialization: str

    def __post_init__(self) -> None:
        if self.minimum_observations <= 0 or not self.ready_condition or not self.initialization:
            raise ValueError("warmup semantics must be explicit and positive")


@dataclass(frozen=True, slots=True)
class OnlyNumericDefinition:
    representation: str = "DECIMAL"
    precision: int = 28
    output_quantum: Decimal | None = None
    rounding: str = "CONTEXT"

    def __post_init__(self) -> None:
        if self.precision <= 0:
            raise ValueError("numeric precision must be positive")


@dataclass(frozen=True, slots=True)
class OnlyCalculationReference:
    node_fingerprint: str | None
    output_name: str
    source: str | None = None

    def __post_init__(self) -> None:
        if (self.node_fingerprint is None) == (self.source is None):
            raise ValueError("input reference must select exactly one node or external source")
        if self.node_fingerprint is not None and len(self.node_fingerprint) != 64:
            raise ValueError("node fingerprint must be a SHA-256 digest")


@dataclass(frozen=True, slots=True)
class OnlyCalculationDefinition:
    kind: OnlyCalculationKind
    type_id: str
    semantic_version: str
    parameters: Mapping[str, OnlyCalculationScalar]
    inputs: tuple[OnlyInputDefinition, ...]
    input_bindings: Mapping[str, OnlyCalculationReference]
    outputs: tuple[OnlyOutputDefinition, ...]
    warmup: OnlyWarmupDefinition
    missing_values: OnlyMissingValuePolicy
    timestamp: OnlyTimestampSemantic
    numeric: OnlyNumericDefinition
    factor_kind: OnlyFactorKind | None = None
    schema_version: int = 1
    extensions: Mapping[str, OnlyCalculationScalar] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.type_id or self.type_id != self.type_id.lower() or "." not in self.type_id:
            raise ValueError("type_id must be a stable lower-case dotted identifier")
        if not self.semantic_version or any(char.isspace() for char in self.semantic_version):
            raise ValueError("semantic_version is required and cannot contain whitespace")
        if self.kind is OnlyCalculationKind.FACTOR and self.factor_kind is None:
            raise ValueError("Factor definition requires factor_kind")
        if self.kind is OnlyCalculationKind.INDICATOR and self.factor_kind is not None:
            raise ValueError("Indicator definition cannot declare factor_kind")
        input_names = tuple(item.name for item in self.inputs)
        output_names = tuple(item.name for item in self.outputs)
        if not output_names or len(input_names) != len(set(input_names)) or len(output_names) != len(set(output_names)):
            raise ValueError("calculation inputs/outputs must be non-empty and uniquely named")
        if set(self.input_bindings) != set(input_names):
            raise ValueError("input bindings must exactly match the input contract")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "input_bindings", MappingProxyType(dict(self.input_bindings)))
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))

    def semantic_payload(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "schema_version": self.schema_version,
                "kind": self.kind,
                "type_id": self.type_id,
                "semantic_version": self.semantic_version,
                "parameters": self.parameters,
                "inputs": self.inputs,
                "input_bindings": self.input_bindings,
                "outputs": self.outputs,
                "warmup": self.warmup,
                "missing_values": self.missing_values,
                "timestamp": self.timestamp,
                "numeric": self.numeric,
                "factor_kind": self.factor_kind,
                "extensions": self.extensions,
            }
        )

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.semantic_payload())

    def to_dict(self) -> Mapping[str, object]:
        payload = only_canonical_payload(self.semantic_payload())
        if not isinstance(payload, Mapping):
            raise TypeError("canonical calculation definition must be an object")
        return MappingProxyType(dict(payload))

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyCalculationDefinition:
        def mapping(name: str) -> Mapping[str, object]:
            value = payload[name]
            if not isinstance(value, Mapping):
                raise ValueError(f"calculation definition {name} must be an object")
            return value

        parameters = mapping("parameters")
        bindings = mapping("input_bindings")
        extensions = mapping("extensions")
        inputs = payload["inputs"]
        outputs = payload["outputs"]
        if not isinstance(inputs, list) or not isinstance(outputs, list):
            raise ValueError("calculation inputs and outputs must be arrays")
        warmup = mapping("warmup")
        numeric = mapping("numeric")
        return cls(
            OnlyCalculationKind(str(payload["kind"])),
            str(payload["type_id"]),
            str(payload["semantic_version"]),
            cast(Mapping[str, OnlyCalculationScalar], parameters),
            tuple(_input_from_dict(item) for item in inputs),
            {str(name): _reference_from_dict(item) for name, item in bindings.items()},
            tuple(_output_from_dict(item) for item in outputs),
            OnlyWarmupDefinition(
                int(str(warmup["minimum_observations"])),
                str(warmup["ready_condition"]),
                OnlyPreReadyOutput(str(warmup["pre_ready_output"])),
                str(warmup["initialization"]),
            ),
            OnlyMissingValuePolicy(str(payload["missing_values"])),
            OnlyTimestampSemantic(str(payload["timestamp"])),
            OnlyNumericDefinition(
                str(numeric["representation"]),
                int(str(numeric["precision"])),
                None if numeric["output_quantum"] is None else Decimal(str(numeric["output_quantum"])),
                str(numeric["rounding"]),
            ),
            None if payload["factor_kind"] is None else OnlyFactorKind(str(payload["factor_kind"])),
            int(str(payload["schema_version"])),
            cast(Mapping[str, OnlyCalculationScalar], extensions),
        )


@dataclass(frozen=True, slots=True)
class OnlyCalculationTypeDefinition:
    kind: OnlyCalculationKind
    type_id: str
    semantic_version: str
    parameters: OnlyParameterSchema
    inputs: tuple[OnlyInputDefinition, ...]
    outputs: tuple[OnlyOutputDefinition, ...]
    missing_values: OnlyMissingValuePolicy
    timestamp: OnlyTimestampSemantic
    numeric: OnlyNumericDefinition
    factor_kind: OnlyFactorKind | None = None

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
        warmup: OnlyWarmupDefinition,
    ) -> OnlyCalculationDefinition:
        return OnlyCalculationDefinition(
            self.kind,
            self.type_id,
            self.semantic_version,
            self.parameters.normalize(parameters),
            self.inputs,
            input_bindings,
            self.outputs,
            warmup,
            self.missing_values,
            self.timestamp,
            self.numeric,
            self.factor_kind,
        )


def _input_from_dict(value: object) -> OnlyInputDefinition:
    if not isinstance(value, Mapping):
        raise ValueError("calculation input must be an object")
    return OnlyInputDefinition(
        str(value["name"]),
        OnlyCalculationDataType(str(value["data_type"])),
        bool(value["nullable"]),
        tuple(str(item) for item in cast(list[object], value["dimensions"])),
        str(value["semantic_type"]),
        None if value["unit"] is None else str(value["unit"]),
    )


def _output_from_dict(value: object) -> OnlyOutputDefinition:
    if not isinstance(value, Mapping):
        raise ValueError("calculation output must be an object")
    return OnlyOutputDefinition(
        str(value["name"]),
        OnlyCalculationDataType(str(value["data_type"])),
        bool(value["nullable"]),
        tuple(str(item) for item in cast(list[object], value["dimensions"])),
        str(value["semantic_type"]),
        None if value["unit"] is None else str(value["unit"]),
    )


def _reference_from_dict(value: object) -> OnlyCalculationReference:
    if not isinstance(value, Mapping):
        raise ValueError("calculation reference must be an object")
    return OnlyCalculationReference(
        None if value["node_fingerprint"] is None else str(value["node_fingerprint"]),
        str(value["output_name"]),
        None if value["source"] is None else str(value["source"]),
    )


# Both names share the one calculation semantic authority; kind validation remains
# part of the immutable definition rather than creating parallel hierarchies.
OnlyIndicatorDefinition = OnlyCalculationDefinition
OnlyFactorDefinition = OnlyCalculationDefinition
