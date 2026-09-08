"""Exact, metadata-only Product projection of one Quant Asset Catalog Generation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, cast

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyFactorKind,
    OnlyMissingValuePolicy,
    OnlyParameterType,
    OnlyTimestampSemantic,
)
from onlyalpha.calculation.implementation import OnlyCalculationStateCapability
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.quant_assets.catalog import OnlyQuantAssetLayer

EXACT_CATALOG_CONTEXT_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROJECTION_DOMAIN = "onlyalpha.exact-catalog-context-projection"
_SCHEMA_DOMAIN = "onlyalpha.exact-catalog-context-schema"


class OnlyExactCatalogContextError(ValueError):
    """Stable fail-closed error at the Exact Catalog Context boundary."""


class OnlyExactCatalogContextNotFound(OnlyExactCatalogContextError):
    def __init__(self) -> None:
        super().__init__("EXACT_CATALOG_CONTEXT_NOT_FOUND")


class OnlyExactCatalogContextUnavailable(OnlyExactCatalogContextError):
    def __init__(self) -> None:
        super().__init__("EXACT_CATALOG_CONTEXT_UNAVAILABLE")


class OnlyExactCatalogContextCorrupt(OnlyExactCatalogContextError):
    def __init__(self) -> None:
        super().__init__("EXACT_CATALOG_CONTEXT_CORRUPT")


class OnlyExactCatalogContextSchemaUnsupported(OnlyExactCatalogContextError):
    def __init__(self) -> None:
        super().__init__("EXACT_CATALOG_CONTEXT_SCHEMA_UNSUPPORTED")


class OnlyExactCatalogContextProjectionMismatch(OnlyExactCatalogContextError):
    def __init__(self) -> None:
        super().__init__("EXACT_CATALOG_CONTEXT_PROJECTION_MISMATCH")


class OnlyExactCatalogGenerationDescriptorReader(Protocol):
    """Read port for one exact, independently verified Catalog descriptor."""

    def load_verified_catalog_descriptor(
        self,
        catalog_generation_fingerprint: str,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class OnlyExactCatalogProviderV1:
    provider_id: str
    provider_version: str
    layer: OnlyQuantAssetLayer
    distribution_name: str
    distribution_version: str
    provider_content_fingerprint: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.provider_id,
                self.provider_version,
                self.distribution_name,
                self.distribution_version,
            )
        ):
            raise OnlyExactCatalogContextCorrupt
        _require_sha(self.provider_content_fingerprint)

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.layer.value, self.provider_id, self.provider_version

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "layer": self.layer.value,
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "provider_content_fingerprint": self.provider_content_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyExactCatalogProviderV1:
        _require_exact_fields(
            payload,
            {
                "provider_id",
                "provider_version",
                "layer",
                "distribution_name",
                "distribution_version",
                "provider_content_fingerprint",
            },
        )
        try:
            return cls(
                _string(payload, "provider_id"),
                _string(payload, "provider_version"),
                OnlyQuantAssetLayer(_string(payload, "layer")),
                _string(payload, "distribution_name"),
                _string(payload, "distribution_version"),
                _string(payload, "provider_content_fingerprint"),
            )
        except (TypeError, ValueError) as exc:
            raise OnlyExactCatalogContextCorrupt from exc


@dataclass(frozen=True, slots=True)
class OnlyExactCatalogCalculationCapabilityV1:
    provider_id: str
    provider_version: str
    provider_layer: OnlyQuantAssetLayer
    kind: OnlyCalculationKind
    type_id: str
    semantic_version: str
    backend: OnlyCalculationBackendKind
    type_descriptor: Mapping[str, object]
    implementation_fingerprint: str
    state_capability: OnlyCalculationStateCapability | None
    checkpoint_schema_version: int | None

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (self.provider_id, self.provider_version, self.type_id, self.semantic_version)
        ):
            raise OnlyExactCatalogContextCorrupt
        _require_sha(self.implementation_fingerprint)
        descriptor = _validated_calculation_type_descriptor(self.type_descriptor)
        if (
            descriptor["kind"] != self.kind.value
            or descriptor["type_id"] != self.type_id
            or descriptor["semantic_version"] != self.semantic_version
        ):
            raise OnlyExactCatalogContextCorrupt
        if self.provider_layer is OnlyQuantAssetLayer.FACTOR:
            if self.kind is not OnlyCalculationKind.FACTOR:
                raise OnlyExactCatalogContextCorrupt
        elif self.kind is OnlyCalculationKind.FACTOR or self.provider_layer is OnlyQuantAssetLayer.STRATEGY:
            raise OnlyExactCatalogContextCorrupt
        if self.backend is OnlyCalculationBackendKind.TRADING:
            if self.state_capability is OnlyCalculationStateCapability.STATELESS:
                if self.checkpoint_schema_version is not None:
                    raise OnlyExactCatalogContextCorrupt
            elif self.state_capability is OnlyCalculationStateCapability.CHECKPOINTABLE:
                if (
                    not isinstance(self.checkpoint_schema_version, int)
                    or isinstance(self.checkpoint_schema_version, bool)
                    or self.checkpoint_schema_version < 1
                ):
                    raise OnlyExactCatalogContextCorrupt
            elif self.checkpoint_schema_version is not None:
                raise OnlyExactCatalogContextCorrupt
        elif self.state_capability is not None or self.checkpoint_schema_version is not None:
            raise OnlyExactCatalogContextCorrupt
        object.__setattr__(self, "type_descriptor", cast(Mapping[str, object], _freeze(descriptor)))

    @property
    def sort_key(self) -> tuple[str, str, str, str, str, str, str]:
        return (
            self.provider_layer.value,
            self.provider_id,
            self.provider_version,
            self.kind.value,
            self.type_id,
            self.semantic_version,
            self.backend.value,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "provider_layer": self.provider_layer.value,
            "kind": self.kind.value,
            "type_id": self.type_id,
            "semantic_version": self.semantic_version,
            "backend": self.backend.value,
            "type_descriptor": _thaw(self.type_descriptor),
            "implementation_fingerprint": self.implementation_fingerprint,
            "state_capability": None if self.state_capability is None else self.state_capability.value,
            "checkpoint_schema_version": self.checkpoint_schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyExactCatalogCalculationCapabilityV1:
        _require_exact_fields(
            payload,
            {
                "provider_id",
                "provider_version",
                "provider_layer",
                "kind",
                "type_id",
                "semantic_version",
                "backend",
                "type_descriptor",
                "implementation_fingerprint",
                "state_capability",
                "checkpoint_schema_version",
            },
        )
        descriptor = payload["type_descriptor"]
        if not isinstance(descriptor, Mapping):
            raise OnlyExactCatalogContextCorrupt
        state = payload["state_capability"]
        checkpoint = payload["checkpoint_schema_version"]
        if state is not None and not isinstance(state, str):
            raise OnlyExactCatalogContextCorrupt
        if checkpoint is not None and (not isinstance(checkpoint, int) or isinstance(checkpoint, bool)):
            raise OnlyExactCatalogContextCorrupt
        try:
            return cls(
                _string(payload, "provider_id"),
                _string(payload, "provider_version"),
                OnlyQuantAssetLayer(_string(payload, "provider_layer")),
                OnlyCalculationKind(_string(payload, "kind")),
                _string(payload, "type_id"),
                _string(payload, "semantic_version"),
                OnlyCalculationBackendKind(_string(payload, "backend")),
                cast(Mapping[str, object], descriptor),
                _string(payload, "implementation_fingerprint"),
                None if state is None else OnlyCalculationStateCapability(state),
                checkpoint,
            )
        except (TypeError, ValueError) as exc:
            raise OnlyExactCatalogContextCorrupt from exc


_PROJECTION_SCHEMA_DESCRIPTOR: Mapping[str, object] = MappingProxyType(
    {
        "domain": _SCHEMA_DOMAIN,
        "schema_version": EXACT_CATALOG_CONTEXT_SCHEMA_VERSION,
        "context_fields": (
            "schema_version",
            "catalog_generation_fingerprint",
            "ordered_providers",
            "ordered_calculation_capabilities",
            "projection_schema_fingerprint",
            "projection_fingerprint",
        ),
        "provider_fields": (
            "provider_id",
            "provider_version",
            "layer",
            "distribution_name",
            "distribution_version",
            "provider_content_fingerprint",
        ),
        "calculation_capability_fields": (
            "provider_id",
            "provider_version",
            "provider_layer",
            "kind",
            "type_id",
            "semantic_version",
            "backend",
            "type_descriptor",
            "implementation_fingerprint",
            "state_capability",
            "checkpoint_schema_version",
        ),
        "calculation_type_descriptor_fields": (
            "kind",
            "type_id",
            "semantic_version",
            "parameters",
            "inputs",
            "outputs",
            "missing_values",
            "timestamp",
            "numeric",
            "factor_kind",
            "execution_shape",
            "semantic_bounds",
        ),
        "parameter_descriptor_fields": (
            "name",
            "parameter_type",
            "required",
            "default",
            "minimum",
            "maximum",
            "enum_values",
            "uppercase",
        ),
        "port_descriptor_fields": ("name", "data_type", "nullable", "dimensions", "semantic_type", "unit"),
        "numeric_descriptor_fields": ("representation", "precision", "output_quantum", "rounding"),
        "provider_order": ("layer", "provider_id", "provider_version"),
        "calculation_capability_order": (
            "provider_layer",
            "provider_id",
            "provider_version",
            "kind",
            "type_id",
            "semantic_version",
            "backend",
        ),
        "layer_discriminants": tuple(item.value for item in OnlyQuantAssetLayer),
        "calculation_kind_discriminants": tuple(item.value for item in OnlyCalculationKind),
        "backend_discriminants": tuple(item.value for item in OnlyCalculationBackendKind),
        "state_capability_discriminants": tuple(item.value for item in OnlyCalculationStateCapability),
        "data_type_discriminants": tuple(item.value for item in OnlyCalculationDataType),
        "parameter_type_discriminants": tuple(item.value for item in OnlyParameterType),
        "missing_value_discriminants": tuple(item.value for item in OnlyMissingValuePolicy),
        "timestamp_discriminants": tuple(item.value for item in OnlyTimestampSemantic),
        "factor_kind_discriminants": tuple(item.value for item in OnlyFactorKind),
    }
)
EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT = only_canonical_fingerprint(_PROJECTION_SCHEMA_DESCRIPTOR)


@dataclass(frozen=True, slots=True)
class OnlyExactCatalogContextV1:
    catalog_generation_fingerprint: str
    ordered_providers: tuple[OnlyExactCatalogProviderV1, ...]
    ordered_calculation_capabilities: tuple[OnlyExactCatalogCalculationCapabilityV1, ...]
    schema_version: int = EXACT_CATALOG_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXACT_CATALOG_CONTEXT_SCHEMA_VERSION:
            raise OnlyExactCatalogContextSchemaUnsupported
        _require_sha(self.catalog_generation_fingerprint)
        if self.ordered_providers != tuple(sorted(self.ordered_providers, key=lambda item: item.sort_key)):
            raise OnlyExactCatalogContextCorrupt
        if self.ordered_calculation_capabilities != tuple(
            sorted(self.ordered_calculation_capabilities, key=lambda item: item.sort_key)
        ):
            raise OnlyExactCatalogContextCorrupt
        if len({item.sort_key for item in self.ordered_providers}) != len(self.ordered_providers):
            raise OnlyExactCatalogContextCorrupt
        if len({item.sort_key for item in self.ordered_calculation_capabilities}) != len(
            self.ordered_calculation_capabilities
        ):
            raise OnlyExactCatalogContextCorrupt

    @property
    def projection_schema_fingerprint(self) -> str:
        return EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT

    @property
    def projection_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": _PROJECTION_DOMAIN,
                **self.to_dict(include_projection_fingerprint=False),
            }
        )

    def to_dict(self, *, include_projection_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "ordered_providers": [item.to_dict() for item in self.ordered_providers],
            "ordered_calculation_capabilities": [item.to_dict() for item in self.ordered_calculation_capabilities],
            "projection_schema_fingerprint": self.projection_schema_fingerprint,
        }
        if include_projection_fingerprint:
            result["projection_fingerprint"] = self.projection_fingerprint
        return result

    def canonical_bytes(self) -> bytes:
        return only_canonical_json(self.to_dict()).encode("utf-8")

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyExactCatalogContextV1:
        _require_exact_fields(
            payload,
            {
                "schema_version",
                "catalog_generation_fingerprint",
                "ordered_providers",
                "ordered_calculation_capabilities",
                "projection_schema_fingerprint",
                "projection_fingerprint",
            },
        )
        schema_version = _integer(payload, "schema_version")
        if schema_version != EXACT_CATALOG_CONTEXT_SCHEMA_VERSION:
            raise OnlyExactCatalogContextSchemaUnsupported
        if _string(payload, "projection_schema_fingerprint") != EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT:
            raise OnlyExactCatalogContextSchemaUnsupported
        providers = _mapping_sequence(payload, "ordered_providers")
        capabilities = _mapping_sequence(payload, "ordered_calculation_capabilities")
        result = cls(
            _string(payload, "catalog_generation_fingerprint"),
            tuple(OnlyExactCatalogProviderV1.from_dict(item) for item in providers),
            tuple(OnlyExactCatalogCalculationCapabilityV1.from_dict(item) for item in capabilities),
            schema_version,
        )
        if _string(payload, "projection_fingerprint") != result.projection_fingerprint:
            raise OnlyExactCatalogContextProjectionMismatch
        return result


class OnlyExactCatalogContextQueryService:
    def __init__(self, reader: OnlyExactCatalogGenerationDescriptorReader) -> None:
        self._reader = reader

    def get_exact_catalog_context(self, catalog_generation_fingerprint: str) -> OnlyExactCatalogContextV1:
        _require_sha(catalog_generation_fingerprint)
        try:
            descriptor = self._reader.load_verified_catalog_descriptor(catalog_generation_fingerprint)
        except OnlyExactCatalogContextError:
            raise
        except Exception as exc:
            raise OnlyExactCatalogContextUnavailable from exc
        return only_project_exact_catalog_context(catalog_generation_fingerprint, descriptor)


def only_project_exact_catalog_context(
    catalog_generation_fingerprint: str,
    descriptor: Mapping[str, object],
) -> OnlyExactCatalogContextV1:
    """Verify one canonical Catalog descriptor and derive its metadata-only projection."""

    _require_sha(catalog_generation_fingerprint)
    _require_exact_fields(descriptor, {"schema_version", "providers", "generation_fingerprint"})
    if _integer(descriptor, "schema_version") != 1:
        raise OnlyExactCatalogContextSchemaUnsupported
    stored_generation = _string(descriptor, "generation_fingerprint")
    if stored_generation != catalog_generation_fingerprint:
        raise OnlyExactCatalogContextCorrupt
    raw_providers = _mapping_sequence(descriptor, "providers")
    if only_canonical_fingerprint({"schema_version": 1, "providers": list(raw_providers)}) != stored_generation:
        raise OnlyExactCatalogContextCorrupt

    providers: list[OnlyExactCatalogProviderV1] = []
    capabilities: list[OnlyExactCatalogCalculationCapabilityV1] = []
    for raw_provider in raw_providers:
        provider, provider_capabilities = _project_provider(raw_provider)
        providers.append(provider)
        capabilities.extend(provider_capabilities)
    ordered_providers = tuple(sorted(providers, key=lambda item: item.sort_key))
    if tuple(providers) != ordered_providers:
        raise OnlyExactCatalogContextCorrupt
    return OnlyExactCatalogContextV1(
        stored_generation,
        ordered_providers,
        tuple(sorted(capabilities, key=lambda item: item.sort_key)),
    )


def _project_provider(
    payload: Mapping[str, object],
) -> tuple[OnlyExactCatalogProviderV1, tuple[OnlyExactCatalogCalculationCapabilityV1, ...]]:
    _require_exact_fields(payload, {"manifest", "content_fingerprint", "calculations", "strategies"})
    manifest = _mapping(payload, "manifest")
    _require_exact_fields(
        manifest,
        {
            "schema_version",
            "provider_id",
            "provider_version",
            "layer",
            "distribution_name",
            "distribution_version",
        },
    )
    if _integer(manifest, "schema_version") != 1:
        raise OnlyExactCatalogContextSchemaUnsupported
    try:
        layer = OnlyQuantAssetLayer(_string(manifest, "layer"))
    except ValueError as exc:
        raise OnlyExactCatalogContextCorrupt from exc
    calculations = _mapping_sequence(payload, "calculations")
    strategies = _mapping_sequence(payload, "strategies")
    canonical_calculations = tuple(sorted(calculations, key=only_canonical_fingerprint))
    canonical_strategies = tuple(sorted(strategies, key=only_canonical_fingerprint))
    if calculations != canonical_calculations or strategies != canonical_strategies:
        raise OnlyExactCatalogContextCorrupt
    for strategy in strategies:
        _validate_strategy_descriptor(strategy)
    if (layer is OnlyQuantAssetLayer.STRATEGY) != (not calculations and bool(strategies)):
        raise OnlyExactCatalogContextCorrupt
    content_fingerprint = _string(payload, "content_fingerprint")
    _require_sha(content_fingerprint)
    if (
        only_canonical_fingerprint(
            {
                "layer": layer.value,
                "calculations": list(calculations),
                "strategies": list(strategies),
            }
        )
        != content_fingerprint
    ):
        raise OnlyExactCatalogContextCorrupt

    provider = OnlyExactCatalogProviderV1(
        _string(manifest, "provider_id"),
        _string(manifest, "provider_version"),
        layer,
        _string(manifest, "distribution_name"),
        _string(manifest, "distribution_version"),
        content_fingerprint,
    )
    result = tuple(_project_calculation(provider, item) for item in calculations)
    return provider, result


def _project_calculation(
    provider: OnlyExactCatalogProviderV1,
    payload: Mapping[str, object],
) -> OnlyExactCatalogCalculationCapabilityV1:
    _require_exact_fields(
        payload,
        {
            "type",
            "backend",
            "implementation_fingerprint",
            "state_capability",
            "checkpoint_schema_version",
        },
    )
    descriptor = _mapping(payload, "type")
    validated = _validated_calculation_type_descriptor(descriptor)
    implementation = payload["implementation_fingerprint"]
    state = payload["state_capability"]
    checkpoint = payload["checkpoint_schema_version"]
    if not isinstance(implementation, str) or implementation == "":
        raise OnlyExactCatalogContextCorrupt
    if state is not None and not isinstance(state, str):
        raise OnlyExactCatalogContextCorrupt
    if checkpoint is not None and (not isinstance(checkpoint, int) or isinstance(checkpoint, bool)):
        raise OnlyExactCatalogContextCorrupt
    try:
        return OnlyExactCatalogCalculationCapabilityV1(
            provider.provider_id,
            provider.provider_version,
            provider.layer,
            OnlyCalculationKind(cast(str, validated["kind"])),
            cast(str, validated["type_id"]),
            cast(str, validated["semantic_version"]),
            OnlyCalculationBackendKind(_string(payload, "backend")),
            validated,
            implementation,
            None if state is None else OnlyCalculationStateCapability(state),
            checkpoint,
        )
    except (TypeError, ValueError) as exc:
        raise OnlyExactCatalogContextCorrupt from exc


def _validated_calculation_type_descriptor(payload: Mapping[str, object]) -> dict[str, object]:
    _require_exact_fields(
        payload,
        {
            "kind",
            "type_id",
            "semantic_version",
            "parameters",
            "inputs",
            "outputs",
            "missing_values",
            "timestamp",
            "numeric",
            "factor_kind",
            "execution_shape",
            "semantic_bounds",
        },
    )
    try:
        kind = OnlyCalculationKind(_string(payload, "kind"))
        OnlyMissingValuePolicy(_string(payload, "missing_values"))
        OnlyTimestampSemantic(_string(payload, "timestamp"))
        execution_shape = OnlyFactorKind(_string(payload, "execution_shape"))
    except ValueError as exc:
        raise OnlyExactCatalogContextCorrupt from exc
    type_id = _string(payload, "type_id")
    semantic_version = _string(payload, "semantic_version")
    if not type_id or not semantic_version:
        raise OnlyExactCatalogContextCorrupt
    factor_kind = payload["factor_kind"]
    if factor_kind is not None:
        if not isinstance(factor_kind, str):
            raise OnlyExactCatalogContextCorrupt
        try:
            parsed_factor_kind = OnlyFactorKind(factor_kind)
        except ValueError as exc:
            raise OnlyExactCatalogContextCorrupt from exc
        if kind is not OnlyCalculationKind.FACTOR or parsed_factor_kind is not execution_shape:
            raise OnlyExactCatalogContextCorrupt
    elif kind is OnlyCalculationKind.FACTOR:
        raise OnlyExactCatalogContextCorrupt
    parameters = _mapping_sequence(payload, "parameters")
    inputs = _mapping_sequence(payload, "inputs")
    outputs = _mapping_sequence(payload, "outputs")
    for parameter in parameters:
        _validate_parameter_descriptor(parameter)
    for port in (*inputs, *outputs):
        _validate_port_descriptor(port)
    if not outputs:
        raise OnlyExactCatalogContextCorrupt
    numeric = _mapping(payload, "numeric")
    _require_exact_fields(numeric, {"representation", "precision", "output_quantum", "rounding"})
    _string(numeric, "representation")
    if _integer(numeric, "precision") < 1:
        raise OnlyExactCatalogContextCorrupt
    if numeric["output_quantum"] is not None and not isinstance(numeric["output_quantum"], str):
        raise OnlyExactCatalogContextCorrupt
    _string(numeric, "rounding")
    bounds = _mapping(payload, "semantic_bounds")
    if set(bounds) != {_string(output, "name") for output in outputs}:
        raise OnlyExactCatalogContextCorrupt
    for value in bounds.values():
        if value is not None and (
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes, bytearray))
            or len(value) != 2
            or any(not isinstance(item, str) for item in value)
        ):
            raise OnlyExactCatalogContextCorrupt
    return {str(name): _thaw(value) for name, value in payload.items()}


def _validate_parameter_descriptor(payload: Mapping[str, object]) -> None:
    _require_exact_fields(
        payload,
        {"name", "parameter_type", "required", "default", "minimum", "maximum", "enum_values", "uppercase"},
    )
    _string(payload, "name")
    try:
        OnlyParameterType(_string(payload, "parameter_type"))
    except ValueError as exc:
        raise OnlyExactCatalogContextCorrupt from exc
    for name in ("required", "uppercase"):
        if not isinstance(payload[name], bool):
            raise OnlyExactCatalogContextCorrupt
    enum_values = payload["enum_values"]
    if not isinstance(enum_values, Sequence) or isinstance(enum_values, (str, bytes, bytearray)):
        raise OnlyExactCatalogContextCorrupt


def _validate_port_descriptor(payload: Mapping[str, object]) -> None:
    _require_exact_fields(payload, {"name", "data_type", "nullable", "dimensions", "semantic_type", "unit"})
    _string(payload, "name")
    try:
        OnlyCalculationDataType(_string(payload, "data_type"))
    except ValueError as exc:
        raise OnlyExactCatalogContextCorrupt from exc
    if not isinstance(payload["nullable"], bool):
        raise OnlyExactCatalogContextCorrupt
    dimensions = payload["dimensions"]
    if (
        not isinstance(dimensions, Sequence)
        or isinstance(dimensions, (str, bytes, bytearray))
        or any(not isinstance(item, str) for item in dimensions)
    ):
        raise OnlyExactCatalogContextCorrupt
    _string(payload, "semantic_type")
    if payload["unit"] is not None and not isinstance(payload["unit"], str):
        raise OnlyExactCatalogContextCorrupt


def _validate_strategy_descriptor(payload: Mapping[str, object]) -> None:
    _require_exact_fields(payload, {"schema_version", "asset_id", "semantic_version", "resources"})
    if _integer(payload, "schema_version") != 1:
        raise OnlyExactCatalogContextSchemaUnsupported
    _string(payload, "asset_id")
    _string(payload, "semantic_version")
    resources = _mapping_sequence(payload, "resources")
    if not resources:
        raise OnlyExactCatalogContextCorrupt
    for resource in resources:
        _require_exact_fields(resource, {"relative_path", "content_sha256", "size"})
        _string(resource, "relative_path")
        _require_sha(_string(resource, "content_sha256"))
        if _integer(resource, "size") < 1:
            raise OnlyExactCatalogContextCorrupt


def _require_sha(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise OnlyExactCatalogContextCorrupt
    return value


def _require_exact_fields(payload: Mapping[str, object], expected: set[str]) -> None:
    if set(payload) != expected:
        raise OnlyExactCatalogContextCorrupt


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise OnlyExactCatalogContextCorrupt
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise OnlyExactCatalogContextCorrupt
    return value


def _mapping(payload: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = payload[name]
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise OnlyExactCatalogContextCorrupt
    return cast(Mapping[str, object], value)


def _mapping_sequence(payload: Mapping[str, object], name: str) -> tuple[Mapping[str, object], ...]:
    value = payload[name]
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise OnlyExactCatalogContextCorrupt
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping) or any(not isinstance(key, str) for key in item):
            raise OnlyExactCatalogContextCorrupt
        result.append(cast(Mapping[str, object], item))
    return tuple(result)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(name): _freeze(item) for name, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(name): _thaw(item) for name, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_thaw(item) for item in value]
    return value


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "EXACT_"))]
