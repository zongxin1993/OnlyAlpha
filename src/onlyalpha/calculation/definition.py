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
CALCULATION_DEFINITION_SCHEMA_VERSION = 2


class OnlyCalculationKind(StrEnum):
    INDICATOR = "INDICATOR"
    FACTOR = "FACTOR"
    TARGET = "TARGET"


class OnlyCalculationBackendKind(StrEnum):
    TRADING = "TRADING"
    RESEARCH = "RESEARCH"


@dataclass(frozen=True, order=True, slots=True)
class OnlyCalculationTypeReference:
    """Backend-neutral exact reference to one semantic calculation type."""

    kind: OnlyCalculationKind
    type_id: str
    semantic_version: str

    def __post_init__(self) -> None:
        if not self.type_id or self.type_id != self.type_id.lower() or "." not in self.type_id:
            raise ValueError("type_id must be a stable lower-case dotted identifier")
        if not self.semantic_version or any(char.isspace() for char in self.semantic_version):
            raise ValueError("semantic_version is required and cannot contain whitespace")

    def to_dict(self) -> Mapping[str, object]:
        return MappingProxyType(
            {"kind": self.kind.value, "type_id": self.type_id, "semantic_version": self.semantic_version}
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyCalculationTypeReference:
        _require_exact_fields(payload, {"kind", "type_id", "semantic_version"}, "calculation type reference")
        return cls(
            OnlyCalculationKind(_require_str(payload, "kind", "calculation type reference")),
            _require_str(payload, "type_id", "calculation type reference"),
            _require_str(payload, "semantic_version", "calculation type reference"),
        )


class OnlyCalculationDataType(StrEnum):
    DECIMAL = "DECIMAL"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    STRING = "STRING"


class OnlyFactorKind(StrEnum):
    TIME_SERIES = "TIME_SERIES"
    CROSS_SECTION = "CROSS_SECTION"


class OnlyFactorScoreDirection(StrEnum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"


FACTOR_VALUE_SEMANTIC_TYPE = "FACTOR_VALUE"
FACTOR_SCORE_SEMANTIC_TYPE = "FACTOR_SCORE"
TARGET_VALUE_SEMANTIC_TYPE = "TARGET_VALUE"


def only_calculation_execution_shape(
    definition: OnlyCalculationDefinition | OnlyCalculationTypeDefinition,
) -> OnlyFactorKind:
    """Return the Definition-owned execution axis without consulting Runtime state."""

    if definition.kind is OnlyCalculationKind.INDICATOR:
        return OnlyFactorKind.TIME_SERIES
    if definition.kind is OnlyCalculationKind.TARGET:
        return OnlyFactorKind.TIME_SERIES
    if definition.factor_kind is None:  # defensive for non-canonical objects
        raise ValueError("Factor calculation requires an execution shape")
    return definition.factor_kind


def only_calculation_semantic_bounds(semantic_type: str) -> tuple[Decimal, Decimal] | None:
    """Return the formal closed value range for bounded port semantics."""

    if semantic_type == FACTOR_SCORE_SEMANTIC_TYPE:
        return Decimal(0), Decimal(1)
    return None


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
    schema_version: int = CALCULATION_DEFINITION_SCHEMA_VERSION
    extensions: Mapping[str, OnlyCalculationScalar] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.schema_version != CALCULATION_DEFINITION_SCHEMA_VERSION:
            raise ValueError(f"unsupported calculation definition schema version: {self.schema_version}")
        if not self.type_id or self.type_id != self.type_id.lower() or "." not in self.type_id:
            raise ValueError("type_id must be a stable lower-case dotted identifier")
        if not self.semantic_version or any(char.isspace() for char in self.semantic_version):
            raise ValueError("semantic_version is required and cannot contain whitespace")
        if self.kind is OnlyCalculationKind.FACTOR and self.factor_kind is None:
            raise ValueError("Factor definition requires factor_kind")
        if self.kind is not OnlyCalculationKind.FACTOR and self.factor_kind is not None:
            raise ValueError(f"{self.kind.value.title()} definition cannot declare factor_kind")
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
        result = dict(payload)
        result["parameters"] = {name: _scalar_to_dict(value) for name, value in self.parameters.items()}
        result["extensions"] = {name: _scalar_to_dict(value) for name, value in self.extensions.items()}
        return MappingProxyType(result)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyCalculationDefinition:
        _require_exact_fields(
            payload,
            {
                "schema_version",
                "kind",
                "type_id",
                "semantic_version",
                "parameters",
                "inputs",
                "input_bindings",
                "outputs",
                "warmup",
                "missing_values",
                "timestamp",
                "numeric",
                "factor_kind",
                "extensions",
            },
            "calculation definition",
        )
        schema_version = _require_int(payload, "schema_version", "calculation definition")
        if schema_version != CALCULATION_DEFINITION_SCHEMA_VERSION:
            raise ValueError(f"unsupported calculation definition schema version: {schema_version}")

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
        _require_exact_fields(
            warmup, {"minimum_observations", "ready_condition", "pre_ready_output", "initialization"}, "warmup"
        )
        _require_exact_fields(numeric, {"representation", "precision", "output_quantum", "rounding"}, "numeric")
        decoded_parameters = {name: _scalar_from_dict(item, "parameters") for name, item in parameters.items()}
        decoded_extensions = {name: _scalar_from_dict(item, "extensions") for name, item in extensions.items()}
        return cls(
            OnlyCalculationKind(_require_str(payload, "kind", "calculation definition")),
            _require_str(payload, "type_id", "calculation definition"),
            _require_str(payload, "semantic_version", "calculation definition"),
            decoded_parameters,
            tuple(_input_from_dict(item) for item in inputs),
            {str(name): _reference_from_dict(item) for name, item in bindings.items()},
            tuple(_output_from_dict(item) for item in outputs),
            OnlyWarmupDefinition(
                _require_int(warmup, "minimum_observations", "warmup"),
                _require_str(warmup, "ready_condition", "warmup"),
                OnlyPreReadyOutput(_require_str(warmup, "pre_ready_output", "warmup")),
                _require_str(warmup, "initialization", "warmup"),
            ),
            OnlyMissingValuePolicy(_require_str(payload, "missing_values", "calculation definition")),
            OnlyTimestampSemantic(_require_str(payload, "timestamp", "calculation definition")),
            OnlyNumericDefinition(
                _require_str(numeric, "representation", "numeric"),
                _require_int(numeric, "precision", "numeric"),
                _require_optional_decimal(numeric, "output_quantum", "numeric"),
                _require_str(numeric, "rounding", "numeric"),
            ),
            None
            if payload["factor_kind"] is None
            else OnlyFactorKind(_require_str(payload, "factor_kind", "calculation definition")),
            schema_version,
            decoded_extensions,
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

    def __post_init__(self) -> None:
        if not self.type_id or self.type_id != self.type_id.lower() or "." not in self.type_id:
            raise ValueError("type_id must be a stable lower-case dotted identifier")
        if not self.semantic_version or any(char.isspace() for char in self.semantic_version):
            raise ValueError("semantic_version is required and cannot contain whitespace")
        if self.kind is OnlyCalculationKind.FACTOR and self.factor_kind is None:
            raise ValueError("Factor type definition requires factor_kind")
        if self.kind is not OnlyCalculationKind.FACTOR and self.factor_kind is not None:
            raise ValueError(f"{self.kind.value.title()} type definition cannot declare factor_kind")
        input_names = tuple(item.name for item in self.inputs)
        output_names = tuple(item.name for item in self.outputs)
        if not output_names or len(input_names) != len(set(input_names)) or len(output_names) != len(set(output_names)):
            raise ValueError("calculation type inputs/outputs must be non-empty and uniquely named")

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

    def descriptor(self) -> Mapping[str, object]:
        """Return deterministic read-only introspection from this canonical contract."""

        payload = only_canonical_payload(
            {
                "kind": self.kind,
                "type_id": self.type_id,
                "semantic_version": self.semantic_version,
                "parameters": self.parameters.fields,
                "inputs": self.inputs,
                "outputs": self.outputs,
                "missing_values": self.missing_values,
                "timestamp": self.timestamp,
                "numeric": self.numeric,
                "factor_kind": self.factor_kind,
                "execution_shape": only_calculation_execution_shape(self),
                "semantic_bounds": {
                    output.name: only_calculation_semantic_bounds(output.semantic_type) for output in self.outputs
                },
            }
        )
        if not isinstance(payload, Mapping):  # pragma: no cover - fixed object payload
            raise TypeError("calculation type descriptor must be an object")
        return cast(Mapping[str, object], _freeze_descriptor(payload))


def _freeze_descriptor(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(name): _freeze_descriptor(item) for name, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_descriptor(item) for item in value)
    return value


def _input_from_dict(value: object) -> OnlyInputDefinition:
    if not isinstance(value, Mapping):
        raise ValueError("calculation input must be an object")
    _require_exact_fields(value, {"name", "data_type", "nullable", "dimensions", "semantic_type", "unit"}, "input")
    return OnlyInputDefinition(
        _require_str(value, "name", "input"),
        OnlyCalculationDataType(_require_str(value, "data_type", "input")),
        _require_bool(value, "nullable", "input"),
        _require_string_array(value, "dimensions", "input"),
        _require_str(value, "semantic_type", "input"),
        _require_optional_str(value, "unit", "input"),
    )


def _output_from_dict(value: object) -> OnlyOutputDefinition:
    if not isinstance(value, Mapping):
        raise ValueError("calculation output must be an object")
    _require_exact_fields(value, {"name", "data_type", "nullable", "dimensions", "semantic_type", "unit"}, "output")
    return OnlyOutputDefinition(
        _require_str(value, "name", "output"),
        OnlyCalculationDataType(_require_str(value, "data_type", "output")),
        _require_bool(value, "nullable", "output"),
        _require_string_array(value, "dimensions", "output"),
        _require_str(value, "semantic_type", "output"),
        _require_optional_str(value, "unit", "output"),
    )


def _reference_from_dict(value: object) -> OnlyCalculationReference:
    if not isinstance(value, Mapping):
        raise ValueError("calculation reference must be an object")
    _require_exact_fields(value, {"node_fingerprint", "output_name", "source"}, "calculation reference")
    return OnlyCalculationReference(
        _require_optional_str(value, "node_fingerprint", "calculation reference"),
        _require_str(value, "output_name", "calculation reference"),
        _require_optional_str(value, "source", "calculation reference"),
    )


def _require_exact_fields(value: Mapping[str, object], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(f"{context} fields are invalid; missing={missing}, unknown={unknown}")


def _require_str(value: Mapping[str, object], name: str, context: str) -> str:
    item = value[name]
    if not isinstance(item, str):
        raise ValueError(f"{context} {name} must be a string")
    return item


def _require_optional_str(value: Mapping[str, object], name: str, context: str) -> str | None:
    item = value[name]
    if item is not None and not isinstance(item, str):
        raise ValueError(f"{context} {name} must be a string or null")
    return item


def _require_int(value: Mapping[str, object], name: str, context: str) -> int:
    item = value[name]
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{context} {name} must be an integer")
    return item


def _require_bool(value: Mapping[str, object], name: str, context: str) -> bool:
    item = value[name]
    if not isinstance(item, bool):
        raise ValueError(f"{context} {name} must be a boolean")
    return item


def _require_string_array(value: Mapping[str, object], name: str, context: str) -> tuple[str, ...]:
    item = value[name]
    if not isinstance(item, list) or any(not isinstance(part, str) for part in item):
        raise ValueError(f"{context} {name} must be an array of strings")
    return tuple(item)


def _require_optional_decimal(value: Mapping[str, object], name: str, context: str) -> Decimal | None:
    item = value[name]
    if item is None:
        return None
    if not isinstance(item, str):
        raise ValueError(f"{context} {name} must be a canonical decimal string or null")
    result = Decimal(item)
    if not result.is_finite():
        raise ValueError(f"{context} {name} must be finite")
    return result


def only_calculation_scalar_to_dict(value: OnlyCalculationScalar) -> Mapping[str, object]:
    """Encode one semantic scalar without losing its declared value type."""

    scalar_type = (
        "NULL"
        if value is None
        else "BOOLEAN"
        if isinstance(value, bool)
        else "INTEGER"
        if isinstance(value, int)
        else "DECIMAL"
        if isinstance(value, Decimal)
        else "STRING"
    )
    canonical_value: object = format(value, "f") if isinstance(value, Decimal) else value
    return {"type": scalar_type, "value": canonical_value}


def only_calculation_scalar_from_dict(value: object, context: str = "calculation") -> OnlyCalculationScalar:
    """Decode the exact scalar representation shared by composition contracts."""

    if not isinstance(value, Mapping):
        raise ValueError(f"{context} scalar must be an object")
    _require_exact_fields(value, {"type", "value"}, f"{context} scalar")
    scalar_type = _require_str(value, "type", f"{context} scalar")
    item = value["value"]
    if scalar_type == "NULL" and item is None:
        return None
    if scalar_type == "BOOLEAN" and isinstance(item, bool):
        return item
    if scalar_type == "INTEGER" and isinstance(item, int) and not isinstance(item, bool):
        return item
    if scalar_type == "DECIMAL" and isinstance(item, str):
        result = Decimal(item)
        if result.is_finite():
            return result
    if scalar_type == "STRING" and isinstance(item, str):
        return item
    raise ValueError(f"{context} scalar type/value are invalid")


def only_calculation_scalar_sort_key(value: OnlyCalculationScalar) -> tuple[str, str]:
    """Return a total, typed order consistent with canonical scalar semantics."""

    encoded = only_calculation_scalar_to_dict(value)
    return str(encoded["type"]), str(encoded["value"])


# Private aliases keep the Definition codec implementation compact while the public
# helpers let composition layers reuse exactly the same scalar authority.
_scalar_to_dict = only_calculation_scalar_to_dict
_scalar_from_dict = only_calculation_scalar_from_dict


# Both names share the one calculation semantic authority; kind validation remains
# part of the immutable definition rather than creating parallel hierarchies.
OnlyIndicatorDefinition = OnlyCalculationDefinition
OnlyFactorDefinition = OnlyCalculationDefinition
