"""Bounded exact registered Chart invocation; no scientific issuance or caller-owned bars."""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from importlib import metadata
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.application.chart_study_input import OnlyChartStudyClosedHistoryInput
from onlyalpha.application.chart_study_manifest import only_chart_study_invocation_manifest
from onlyalpha.application.market_data_stream import OnlyChartStudyPreviewInput
from onlyalpha.calculation.chart_decimal import (
    OnlyChartNumericBindingVerifier,
    only_chart_study_effective_numeric,
    only_chart_study_numeric_binding,
)
from onlyalpha.calculation.chart_study import OnlyChartStudySupport
from onlyalpha.calculation.decimal_execution import only_decimal_context, only_decimal_execution_semantic_dependency
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationTypeDefinition,
    OnlyFactorKind,
    OnlyParameterType,
    OnlyTimestampSemantic,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationImplementationManifest,
    only_chart_study_numeric_dependency,
    only_distribution_semantic_dependency,
    only_python_stdlib_semantic_dependency,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.quant_assets.catalog import OnlyQuantAssetCatalogGeneration, OnlyQuantAssetKind, OnlyQuantAssetProvider
from onlyalpha.quant_assets.installed_implementation import (
    only_require_installed_distribution_module,
    only_require_installed_implementation,
    only_require_loaded_python_code,
    only_require_manifest_resources,
)
from onlyalpha.research.calculation.backend import (
    OnlyChartStudyCalculationBackend,
    OnlyResearchCalculationBackendExecutionV2,
)
from onlyalpha.research.calculation.output_validation import only_validate_research_outputs
from onlyalpha.research.calculation.readiness import only_validate_research_output_readiness

MAX_INPUT_ROWS = 2000
MAX_PERIOD = 10000
_BAR_FIELDS = frozenset({"bar.open", "bar.high", "bar.low", "bar.close", "bar.volume", "bar.start_ns"})


@dataclass(frozen=True, slots=True)
class OnlyChartStudyAdmission:
    """Exact process-local Chart permission; not formal Research publication admission."""

    catalog: OnlyQuantAssetCatalogGeneration
    provider: OnlyQuantAssetProvider
    registration: OnlyCalculationBackendRegistration
    invocation_manifest: OnlyCalculationImplementationManifest
    support: OnlyChartStudySupport
    catalog_generation_fingerprint: str
    provider_content_fingerprint: str

    def payload(self) -> dict[str, object]:
        manifest = self.registration.implementation_manifest
        if manifest is None:
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        return {
            "domain": "onlyalpha.chart-study.capability-projection",
            "schema_version": 2,
            "source_kind": "CHART_STUDY_TRANSIENT",
            "authority": "DISPLAY_ONLY",
            "publication_status": "NOT_A_RESEARCH_RESULT",
            "descriptor": self.registration.type_definition.descriptor(),
            "backend": self.registration.backend.value,
            "implementation": manifest.to_dict(),
            "invocation": self.invocation_manifest.to_dict(),
            "provider_manifest": self.provider.manifest.to_dict(),
            "provider_content_fingerprint": self.provider_content_fingerprint,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "readiness_contract_versions": [1],
            "output_members": [item.output_name for item in self.support.series],
            "supported_shape": "TIME_SERIES/BAR_FIELDS",
            "input_support": {
                "instrument_policy": "EXACT_SOURCE_CATALOG",
                "resolution_mode": "PROVIDER_NATIVE",
                "bar_formation": "FIXED_DURATION",
                "alignment": "UTC_24X7",
                "closed_only": False,
                "preview_mode": "OWNING_STREAM_SNAPSHOT",
                "coverage_policy": "COMPLETE_VERIFIED_WINDOW",
            },
            "finite_initialization": "PARTIAL_WINDOW_AT_EXPLICIT_FINITE_START",
            "limits": {"max_input_rows": MAX_INPUT_ROWS, "max_period": MAX_PERIOD, "max_concurrent_invocations": 1},
            "numeric_binding": only_chart_study_numeric_binding(self.registration.type_definition.numeric),
            "presentation": self.support.to_dict(),
        }

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.payload())


class OnlyChartStudyInvocation:
    """Calls installed backend methods over authorized owning-reader handoffs only."""

    def __init__(self, registry: OnlyCalculationRegistry, catalog: OnlyQuantAssetCatalogGeneration) -> None:
        from threading import Lock

        self._registry = registry
        self._catalog = catalog
        self._slot = Lock()
        self._admissions = self._admit()
        self._fingerprints = tuple(item.fingerprint for item in self._admissions)

    @property
    def admissions(self) -> tuple[OnlyChartStudyAdmission, ...]:
        self._require_current()
        return self._admissions

    def admission_for(self, type_id: str, semantic_version: str) -> OnlyChartStudyAdmission:
        self._require_current()
        matches = [
            item
            for item in self._admissions
            if (item.registration.type_definition.type_id, item.registration.type_definition.semantic_version)
            == (type_id, semantic_version)
        ]
        if len(matches) != 1:
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        return matches[0]

    def _admit(self) -> tuple[OnlyChartStudyAdmission, ...]:
        try:
            return self._verify_admission()
        except ValueError as error:
            if str(error).startswith("CHART_STUDY_"):
                raise
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE") from error
        except (OSError, LookupError, TypeError, SyntaxError, ImportError, AttributeError) as error:
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE") from error

    def _verify_admission(self) -> tuple[OnlyChartStudyAdmission, ...]:
        if type(self) is not OnlyChartStudyInvocation:
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        if len({p.manifest.provider_id for p in self._catalog.providers}) != len(self._catalog.providers):
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        if len(self._catalog._installed_origins) != len(self._catalog.providers):
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        checked_resources = set()
        provider_fingerprints = {}
        for provider in self._catalog.providers:
            content_fingerprint = provider.content_fingerprint
            provider_fingerprints[provider.manifest.provider_id] = content_fingerprint
            origins = [item for item in self._catalog._installed_origins if item.provider is provider]
            if (
                len(origins) != 1
                or origins[0].manifest_fingerprint != only_canonical_fingerprint(provider.manifest.to_dict())
                or origins[0].content_fingerprint != content_fingerprint
            ):
                raise ValueError("CHART_STUDY_UNAVAILABLE")
            module, factory_name = origins[0].entrypoint_identity.split(":")
            factory: object = sys.modules.get(module)
            for part in factory_name.split("."):
                factory = getattr(factory, part, None)
            if factory is not origins[0].factory:
                raise ValueError("CHART_STUDY_UNAVAILABLE")
            only_require_installed_distribution_module(
                provider.manifest.distribution_name, provider.manifest.distribution_version, module
            )
            path = Path(str(getattr(sys.modules.get(module), "__file__", "")))
            only_require_loaded_python_code(module, path.read_bytes(), path.resolve())
            for registration in provider.calculation_registrations:
                descriptor = registration.type_definition
                if (
                    self._registry.resolve(
                        descriptor.kind, descriptor.type_id, descriptor.semantic_version, registration.backend
                    )
                    is not registration
                ):
                    raise ValueError("CHART_STUDY_UNAVAILABLE")
                if registration.implementation_manifest is None:
                    raise ValueError("CHART_STUDY_UNAVAILABLE")
                resource_key = (
                    provider.manifest.distribution_name,
                    provider.manifest.distribution_version,
                    registration.implementation_manifest.entrypoint_identity,
                    registration.implementation_manifest.resources,
                )
                if resource_key not in checked_resources:
                    only_require_manifest_resources(
                        registration.implementation_manifest,
                        provider.manifest.distribution_name,
                        provider.manifest.distribution_version,
                    )
                    checked_resources.add(resource_key)
        invocation = only_chart_study_invocation_manifest()
        root = Path(__file__).resolve().parents[1]
        for resource in invocation.resources:
            path = root / resource.relative_path
            module = "onlyalpha." + resource.relative_path[:-3].replace("/", ".")
            only_require_installed_distribution_module("onlyalpha", metadata.version("onlyalpha"), module)
            only_require_loaded_python_code(module, path.read_bytes(), path)
        admissions = []
        checked_implementations: set[tuple[object, ...]] = set()
        catalog_fingerprint = self._catalog.generation_fingerprint
        for provider in self._catalog.providers:
            if provider.manifest.kind is not OnlyQuantAssetKind.INDICATOR:
                continue
            for registration in provider.calculation_registrations:
                if registration.backend is not OnlyCalculationBackendKind.RESEARCH:
                    continue
                if not isinstance(registration.provider, OnlyChartStudyCalculationBackend):
                    continue
                support = registration.provider.chart_study_support(registration.type_definition)
                if support is None:
                    continue
                _require_chart_registration(registration, support, checked_implementations=checked_implementations)
                admissions.append(
                    OnlyChartStudyAdmission(
                        self._catalog,
                        provider,
                        registration,
                        invocation,
                        support,
                        catalog_fingerprint,
                        provider_fingerprints[provider.manifest.provider_id],
                    )
                )
        if not admissions:
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        return tuple(
            sorted(
                admissions,
                key=lambda item: (
                    item.registration.type_definition.type_id,
                    item.registration.type_definition.semantic_version,
                ),
            )
        )

    def _require_current(self) -> None:
        current = self._admit()
        if tuple(item.fingerprint for item in current) != self._fingerprints:
            raise ValueError("CHART_STUDY_REGISTRATION_CHANGED")
        if any(
            a.registration is not b.registration or a.provider is not b.provider
            for a, b in zip(current, self._admissions, strict=True)
        ):
            raise ValueError("CHART_STUDY_UNAVAILABLE")

    def invoke_closed_history(
        self,
        parameters: Mapping[str, object],
        inputs: OnlyChartStudyClosedHistoryInput,
        *,
        type_id: str,
        semantic_version: str,
        capability_fingerprint: str,
    ) -> OnlyResearchCalculationBackendExecutionV2:
        closed, _ = self.invoke_owned_inputs(
            parameters,
            inputs,
            type_id=type_id,
            semantic_version=semantic_version,
            capability_fingerprint=capability_fingerprint,
        )
        return closed

    def invoke_owned_inputs(
        self,
        parameters: Mapping[str, object],
        inputs: OnlyChartStudyClosedHistoryInput,
        *,
        type_id: str,
        semantic_version: str,
        capability_fingerprint: str,
        preview: OnlyChartStudyPreviewInput | None = None,
    ) -> tuple[OnlyResearchCalculationBackendExecutionV2, OnlyResearchCalculationBackendExecutionV2 | None]:
        if type(inputs) is not OnlyChartStudyClosedHistoryInput or (
            preview is not None and type(preview) is not OnlyChartStudyPreviewInput
        ):
            raise ValueError("CHART_STUDY_INPUT_UNAVAILABLE")
        if not self._slot.acquire(blocking=False):
            raise ValueError("CHART_STUDY_CAPACITY_EXCEEDED")
        try:
            admission = self.admission_for(type_id, semantic_version)
            resolver = admission.registration.definition_resolver
            assert resolver is not None
            _require_chart_parameters(admission.registration.type_definition, parameters)
            definition = resolver.resolve(parameters, {})
            _require_chart_definition(definition, admission.registration.type_definition, parameters)
            window = inputs.require_window()
            columns = self._bar_columns(definition, window.bars)
            result = self._execute_numeric(
                parameters,
                columns,
                type_id=type_id,
                semantic_version=semantic_version,
                capability_fingerprint=capability_fingerprint,
            )
            preview_result = None
            if preview is not None:
                try:
                    live = preview.require_preview()
                    stride = window.bar_semantic.stride_minutes * 60_000_000_000
                    if (
                        live.closed
                        or live.bar_start_ns != window.resolved_end_ns
                        or live.bar_end_ns != live.bar_start_ns + stride
                        or str(live.instrument_id) != window.instrument_id
                        or str(live.source_id) != window.source_selection.source_id
                    ):
                        raise ValueError("CHART_STUDY_PREVIEW_UNAVAILABLE")
                    with localcontext(only_decimal_context(only_chart_study_effective_numeric(definition.numeric))):
                        extended = self._bar_columns(definition, (*window.bars, live))
                    full = self._execute_numeric(
                        parameters,
                        extended,
                        type_id=type_id,
                        semantic_version=semantic_version,
                        capability_fingerprint=capability_fingerprint,
                        preview_row=True,
                    )
                    preview_result = OnlyResearchCalculationBackendExecutionV2(
                        MappingProxyType(
                            {name: value.slice(len(value) - 1, 1) for name, value in full.outputs.items()}
                        ),
                        MappingProxyType(
                            {
                                name: type(value)(
                                    value.states.slice(len(value.states) - 1, 1),
                                    value.reasons.slice(len(value.reasons) - 1, 1),
                                )
                                for name, value in full.readiness.items()
                            }
                        ),
                    )
                    preview.require_current()
                except ValueError as error:
                    if str(error) != "CHART_STUDY_PREVIEW_UNAVAILABLE":
                        raise
                    preview_result = None
            inputs.require_window()
            self._require_current()
            return result, preview_result
        finally:
            self._slot.release()

    @staticmethod
    def _bar_columns(definition: OnlyCalculationDefinition, bars: tuple[object, ...]) -> dict[str, pa.Array]:
        columns = {}
        for port in definition.inputs:
            binding = definition.input_bindings[port.name]
            name = binding.source.removeprefix("bar.") if binding.source is not None else ""
            attribute = "bar_start_ns" if name == "start_ns" else name
            values = [getattr(bar, attribute) for bar in bars]
            if port.data_type is OnlyCalculationDataType.INTEGER:
                columns[port.name] = pa.array(values, type=pa.int64())
            else:
                if any(type(value) is not str or len(value) > 64 for value in values):
                    raise ValueError("CHART_STUDY_INPUT_INVALID")
                columns[port.name] = pa.array([Decimal(value) for value in values], type=pa.decimal128(38, 18))
        return columns

    def _invoke_numeric(
        self,
        parameters: Mapping[str, object],
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
        *,
        type_id: str,
        semantic_version: str,
        capability_fingerprint: str,
    ) -> OnlyResearchCalculationBackendExecutionV2:
        if not self._slot.acquire(blocking=False):
            raise ValueError("CHART_STUDY_CAPACITY_EXCEEDED")
        try:
            return self._execute_numeric(
                parameters,
                inputs,
                type_id=type_id,
                semantic_version=semantic_version,
                capability_fingerprint=capability_fingerprint,
            )
        finally:
            self._slot.release()

    def _execute_numeric(
        self,
        parameters: Mapping[str, object],
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
        *,
        type_id: str,
        semantic_version: str,
        capability_fingerprint: str,
        preview_row: bool = False,
    ) -> OnlyResearchCalculationBackendExecutionV2:
        admission = self.admission_for(type_id, semantic_version)
        if type(capability_fingerprint) is not str or re.fullmatch(r"[0-9a-f]{64}", capability_fingerprint) is None:
            raise ValueError("CHART_STUDY_INPUT_INVALID")
        if capability_fingerprint != admission.fingerprint:
            raise ValueError("CHART_STUDY_REGISTRATION_CHANGED")
        registration = admission.registration
        assert registration.definition_resolver is not None
        _require_chart_parameters(registration.type_definition, parameters)
        definition = registration.definition_resolver.resolve(parameters, {})
        _require_chart_definition(definition, registration.type_definition, parameters)
        if not isinstance(inputs, Mapping) or set(inputs) != {port.name for port in definition.inputs}:
            raise ValueError("CHART_STUDY_INPUT_INVALID")
        lengths = set()
        for port in definition.inputs:
            array = inputs[port.name]
            if not isinstance(array, (pa.Array, pa.ChunkedArray)) or array.null_count:
                raise ValueError("CHART_STUDY_INPUT_INVALID")
            valid_type = (
                pa.types.is_int64(array.type)
                if port.data_type is OnlyCalculationDataType.INTEGER
                else (pa.types.is_decimal128(array.type) and 0 <= array.type.scale <= 18)
            )
            if (
                not valid_type
                or not 1 <= len(array) <= MAX_INPUT_ROWS + int(preview_row)
                or isinstance(array, pa.ChunkedArray)
                and array.num_chunks > MAX_INPUT_ROWS + int(preview_row)
            ):
                raise ValueError("CHART_STUDY_INPUT_INVALID")
            lengths.add(len(array))
        if len(lengths) != 1:
            raise ValueError("CHART_STUDY_INPUT_INVALID")
        rows = lengths.pop()
        backend = cast(OnlyChartStudyCalculationBackend, registration.provider)
        with localcontext(only_decimal_context(only_chart_study_effective_numeric(definition.numeric))):
            result = backend.execute_chart_study(definition, inputs)
            outputs = only_validate_research_outputs(definition, result.outputs, rows)
            only_validate_research_output_readiness(definition, outputs, result.readiness, row_count=rows)
            if any(
                state.as_py() not in {"PARTIAL", "READY", "UNAVAILABLE"}
                for value in result.readiness.values()
                for state in value.states
            ):
                raise ValueError("CHART_STUDY_OUTPUT_INVALID")
            self._require_current()
            return OnlyResearchCalculationBackendExecutionV2(outputs, MappingProxyType(dict(result.readiness)))


def _require_chart_parameters(descriptor: OnlyCalculationTypeDefinition, parameters: Mapping[str, object]) -> None:
    """Preserve typed Product input; the general resolver's coercions are not Chart permission."""
    types = {
        OnlyParameterType.INTEGER: int,
        OnlyParameterType.DECIMAL: Decimal,
        OnlyParameterType.STRING: str,
        OnlyParameterType.BOOLEAN: bool,
    }
    fields = {item.name: item for item in descriptor.parameters.fields}
    if not isinstance(parameters, Mapping) or len(parameters) > 16 or set(parameters) - set(fields):
        raise ValueError("CHART_STUDY_INPUT_INVALID")
    if parameters.get("price_field", "CLOSE") != "CLOSE":
        raise ValueError("CHART_STUDY_INPUT_INVALID")
    for name, value in parameters.items():
        if type(value) is not types[fields[name].parameter_type]:
            raise ValueError("CHART_STUDY_INPUT_INVALID")
        if type(value) is int and not 1 <= value <= MAX_PERIOD:
            raise ValueError("CHART_STUDY_INPUT_INVALID")
        if isinstance(value, Decimal) and (not value.is_finite() or len(str(value)) > 64):
            raise ValueError("CHART_STUDY_INPUT_INVALID")
    try:
        normalized = descriptor.parameters.normalize(parameters)
    except (ValueError, TypeError, ArithmeticError) as error:
        raise ValueError("CHART_STUDY_INPUT_INVALID") from error
    if normalized.get("price_field", "CLOSE") != "CLOSE":
        raise ValueError("CHART_STUDY_INPUT_INVALID")


def _require_chart_definition(
    definition: OnlyCalculationDefinition, descriptor: OnlyCalculationTypeDefinition, parameters: Mapping[str, object]
) -> None:
    if (
        definition.kind is not descriptor.kind
        or definition.type_id != descriptor.type_id
        or definition.semantic_version != descriptor.semantic_version
        or dict(definition.parameters) != dict(descriptor.parameters.normalize(parameters))
        or definition.inputs != descriptor.inputs
        or definition.outputs != descriptor.outputs
        or definition.numeric != descriptor.numeric
        or definition.timestamp is not OnlyTimestampSemantic.EVENT_TIME
        or definition.extensions
        or set(definition.input_bindings) != {item.name for item in descriptor.inputs}
        or any(
            binding.source not in _BAR_FIELDS or binding.node_fingerprint is not None or binding.output_name != name
            for name, binding in definition.input_bindings.items()
        )
    ):
        raise ValueError("CHART_STUDY_UNAVAILABLE")
    if definition.parameters.get("price_field", "CLOSE") != "CLOSE":
        raise ValueError("CHART_STUDY_INPUT_INVALID")
    only_chart_study_effective_numeric(definition.numeric)


def _require_chart_registration(
    registration: OnlyCalculationBackendRegistration,
    support: OnlyChartStudySupport,
    *,
    checked_implementations: set[tuple[object, ...]] | None = None,
) -> None:
    descriptor = registration.type_definition
    if (
        descriptor.kind is not OnlyCalculationKind.INDICATOR
        or descriptor.execution_shape is not OnlyFactorKind.TIME_SERIES
        or descriptor.timestamp is not OnlyTimestampSemantic.EVENT_TIME
        or not descriptor.inputs
        or len(descriptor.inputs) > 8
        or not descriptor.outputs
        or len(descriptor.outputs) > 8
        or any(
            port.data_type not in {OnlyCalculationDataType.DECIMAL, OnlyCalculationDataType.INTEGER}
            for port in descriptor.inputs
        )
        or registration.backend is not OnlyCalculationBackendKind.RESEARCH
        or registration.definition_resolver is None
        or getattr(registration.definition_resolver, "type_definition", None) is not descriptor
        or not isinstance(registration.provider, OnlyChartStudyCalculationBackend)
        or not isinstance(registration.provider, OnlyChartNumericBindingVerifier)
        or vars(registration.provider)
    ):
        raise ValueError("CHART_STUDY_UNAVAILABLE")
    required = {
        only_decimal_execution_semantic_dependency(),
        only_chart_study_numeric_dependency(),
        only_python_stdlib_semantic_dependency("decimal"),
        only_distribution_semantic_dependency("pyarrow"),
    }
    manifest = registration.implementation_manifest
    if manifest is None or not required.issubset(manifest.semantic_dependencies):
        raise ValueError("CHART_STUDY_DEPENDENCY_UNAVAILABLE")
    if type(support) is not OnlyChartStudySupport or not 1 <= len(support.series) <= 8:
        raise ValueError("CHART_STUDY_UNAVAILABLE")
    numeric = {port.name for port in descriptor.outputs if port.data_type is OnlyCalculationDataType.DECIMAL}
    names = [series.output_name for series in support.series]
    if (
        len(set(names)) != len(names)
        or not set(names).issubset(numeric)
        or type(support.preview_supported) is not bool
        or type(support.default_variant) is not bool
        or support.placement not in {"PRICE_OVERLAY", "SEPARATE_PANE"}
        or any(
            s.kind not in {"LINE", "HISTOGRAM"}
            or s.unit not in {"PRICE", "RATIO", "VOLUME", "SCALAR"}
            or re.fullmatch(r"#[0-9a-fA-F]{6}", s.color) is None
            for s in support.series
        )
        or support.fill is not None
        and (len(support.fill) != 2 or not set(support.fill).issubset(names))
    ):
        raise ValueError("CHART_STUDY_UNAVAILABLE")
    definition = registration.definition_resolver.resolve(support.default_parameters, {})
    _require_chart_definition(definition, descriptor, support.default_parameters)
    implementation_key = (manifest.entrypoint_identity, manifest.resources, type(registration.provider))
    if checked_implementations is None or implementation_key not in checked_implementations:
        only_require_installed_implementation(manifest, registration.provider)
        if checked_implementations is not None:
            checked_implementations.add(implementation_key)
    cast(OnlyChartNumericBindingVerifier, registration.provider).require_chart_numeric_binding(descriptor.numeric)
