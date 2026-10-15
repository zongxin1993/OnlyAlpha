"""Bounded disposable SMA SPI invocation; no Product endpoint or scientific issuance."""

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
from onlyalpha.calculation.chart_decimal import (
    OnlyChartNumericBindingVerifier,
    only_chart_sma_effective_numeric,
    only_chart_sma_numeric_binding,
)
from onlyalpha.calculation.decimal_execution import only_decimal_context, only_decimal_execution_semantic_dependency
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
    OnlyFactorKind,
    OnlyInputDefinition,
    OnlyMissingValuePolicy,
    OnlyOutputDefinition,
    OnlyPreReadyOutput,
    OnlyTimestampSemantic,
    OnlyWarmupDefinition,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationImplementationManifest,
    only_chart_sma_numeric_dependency,
    only_chart_study_invocation_dependency,
    only_chart_study_invocation_manifest,
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
    OnlyResearchCalculationBackendExecutionV2,
    OnlyResearchReadinessCalculationBackend,
)
from onlyalpha.research.calculation.output_validation import only_validate_research_outputs
from onlyalpha.research.calculation.readiness import only_validate_research_output_readiness

SMA_REFERENCE = OnlyCalculationTypeReference(OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.sma", "1")
MAX_INPUT_ROWS = 2000
MAX_PERIOD = 10000


@dataclass(frozen=True, slots=True)
class OnlyChartStudySmaAdmission:
    """Process-local projection identity, never source authority or scientific Evidence."""

    catalog: OnlyQuantAssetCatalogGeneration
    provider: OnlyQuantAssetProvider
    registration: OnlyCalculationBackendRegistration
    invocation_manifest: OnlyCalculationImplementationManifest

    def payload(self) -> dict[str, object]:
        registration = self.registration
        manifest = registration.implementation_manifest
        if manifest is None:
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        return {
            "domain": "onlyalpha.chart-study.capability-projection",
            "schema_version": 1,
            "source_kind": "CHART_STUDY_TRANSIENT",
            "authority": "DISPLAY_ONLY",
            "publication_status": "NOT_A_RESEARCH_RESULT",
            "descriptor": registration.type_definition.descriptor(),
            "backend": registration.backend.value,
            "implementation": manifest.to_dict(),
            "invocation": self.invocation_manifest.to_dict(),
            "provider_manifest": self.provider.manifest.to_dict(),
            "provider_content_fingerprint": self.provider.content_fingerprint,
            "catalog_generation_fingerprint": self.catalog.generation_fingerprint,
            "readiness_contract_versions": list(registration.readiness_contract_versions),
            "output_members": [item.name for item in registration.type_definition.outputs],
            "supported_shape": "TIME_SERIES/CLOSED_HISTORY/CLOSE/value",
            "input_support": {
                "instrument_policy": "EXACT_SOURCE_CATALOG",
                "resolution_mode": "PROVIDER_NATIVE",
                "bar_formation": "FIXED_DURATION",
                "alignment": "UTC_24X7",
                "closed_only": True,
                "coverage_policy": "COMPLETE_VERIFIED_WINDOW",
            },
            "finite_initialization": "PARTIAL_WINDOW_AT_EXPLICIT_FINITE_START",
            "limits": {"max_input_rows": MAX_INPUT_ROWS, "max_period": MAX_PERIOD, "max_concurrent_invocations": 1},
            "numeric_binding": only_chart_sma_numeric_binding(registration.type_definition.numeric),
        }

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.payload())


class OnlyChartStudySmaInvocation:
    """Installed numeric consumer of owning authorized complete-history handoffs.

    Raw Arrow is restricted to the private numeric kernel, never admitted closed history.
    No writer, acquisition, command or Research executor is accepted by this object.
    """

    def __init__(self, registry: OnlyCalculationRegistry, catalog: OnlyQuantAssetCatalogGeneration) -> None:
        from threading import Lock

        self._registry = registry
        self._catalog = catalog
        self._slot = Lock()
        self._admission = self._admit()
        self._fingerprint = self._admission.fingerprint

    @property
    def admission(self) -> OnlyChartStudySmaAdmission:
        self._require_current()
        return self._admission

    def _admit(self) -> OnlyChartStudySmaAdmission:
        try:
            return self._verify_admission()
        except ValueError as error:
            if str(error).startswith("CHART_STUDY_"):
                raise
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE") from error
        except (OSError, LookupError, TypeError, SyntaxError, ImportError, AttributeError) as error:
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE") from error

    def _verify_admission(self) -> OnlyChartStudySmaAdmission:
        if type(self) is not OnlyChartStudySmaInvocation:
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        registration = self._registry.resolve(
            SMA_REFERENCE.kind,
            SMA_REFERENCE.type_id,
            SMA_REFERENCE.semantic_version,
            OnlyCalculationBackendKind.RESEARCH,
        )
        owners = [
            provider
            for provider in self._catalog.providers
            if any(item is registration for item in provider.calculation_registrations)
        ]
        if len(owners) != 1 or owners[0].manifest.kind is not OnlyQuantAssetKind.INDICATOR:
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        if len({item.manifest.provider_id for item in self._catalog.providers}) != len(self._catalog.providers):
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        if len(self._catalog._installed_origins) != len(self._catalog.providers):
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        for provider in self._catalog.providers:
            matches = [item for item in self._catalog._installed_origins if item.provider is provider]
            if (
                len(matches) != 1
                or matches[0].manifest_fingerprint != only_canonical_fingerprint(provider.manifest.to_dict())
                or matches[0].content_fingerprint != provider.content_fingerprint
            ):
                raise ValueError("CHART_STUDY_UNAVAILABLE")
            factory_module, factory_name = matches[0].entrypoint_identity.split(":")
            factory_object: object = sys.modules.get(factory_module)
            for part in factory_name.split("."):
                factory_object = getattr(factory_object, part, None)
            if factory_object is not matches[0].factory:
                raise ValueError("CHART_STUDY_UNAVAILABLE")
            only_require_installed_distribution_module(
                provider.manifest.distribution_name, provider.manifest.distribution_version, factory_module
            )
            factory_path = Path(str(getattr(sys.modules.get(factory_module), "__file__", "")))
            only_require_loaded_python_code(factory_module, factory_path.read_bytes(), factory_path.resolve())
            for item in provider.calculation_registrations:
                definition = item.type_definition
                if (
                    self._registry.resolve(
                        definition.kind, definition.type_id, definition.semantic_version, item.backend
                    )
                    is not item
                ):
                    raise ValueError("CHART_STUDY_UNAVAILABLE")
                if item.implementation_manifest is None:
                    raise ValueError("CHART_STUDY_UNAVAILABLE")
                only_require_manifest_resources(
                    item.implementation_manifest,
                    provider.manifest.distribution_name,
                    provider.manifest.distribution_version,
                )
        _require_sma_registration(registration)
        invocation = only_chart_study_invocation_manifest()
        root = Path(__file__).resolve().parents[1]
        for resource in invocation.resources:
            path = root / resource.relative_path
            module = "onlyalpha." + resource.relative_path[:-3].replace("/", ".")
            only_require_installed_distribution_module("onlyalpha", metadata.version("onlyalpha"), module)
            only_require_loaded_python_code(module, path.read_bytes(), path)
        return OnlyChartStudySmaAdmission(self._catalog, owners[0], registration, invocation)

    def _require_current(self) -> None:
        current = self._admit()
        if current.fingerprint != self._fingerprint:
            raise ValueError("CHART_STUDY_REGISTRATION_CHANGED")
        if current.registration is not self._admission.registration or current.provider is not self._admission.provider:
            raise ValueError("CHART_STUDY_UNAVAILABLE")

    def invoke_closed_history(
        self,
        parameters: Mapping[str, object],
        inputs: OnlyChartStudyClosedHistoryInput,
        *,
        capability_fingerprint: str,
    ) -> OnlyResearchCalculationBackendExecutionV2:
        if type(inputs) is not OnlyChartStudyClosedHistoryInput:
            raise ValueError("CHART_STUDY_INPUT_UNAVAILABLE")
        if not self._slot.acquire(blocking=False):
            raise ValueError("CHART_STUDY_CAPACITY_EXCEEDED")
        try:
            self._require_current()
            window = inputs.require_window()
            with localcontext(
                only_decimal_context(
                    only_chart_sma_effective_numeric(self._admission.registration.type_definition.numeric)
                )
            ):
                if any(len(bar.close) > 64 for bar in window.bars):
                    raise ValueError("CHART_STUDY_INPUT_INVALID")
                values = {"value": pa.array([Decimal(bar.close) for bar in window.bars], type=pa.decimal128(38, 18))}
                result = self._execute_numeric(parameters, values, capability_fingerprint=capability_fingerprint)
                inputs.require_window()
                return result
        finally:
            self._slot.release()

    def _invoke_numeric(
        self,
        parameters: Mapping[str, object],
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
        *,
        capability_fingerprint: str,
    ) -> OnlyResearchCalculationBackendExecutionV2:
        if not self._slot.acquire(blocking=False):
            raise ValueError("CHART_STUDY_CAPACITY_EXCEEDED")
        try:
            return self._execute_numeric(parameters, inputs, capability_fingerprint=capability_fingerprint)
        finally:
            self._slot.release()

    def _execute_numeric(
        self,
        parameters: Mapping[str, object],
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
        *,
        capability_fingerprint: str,
    ) -> OnlyResearchCalculationBackendExecutionV2:
        self._require_current()
        if type(capability_fingerprint) is not str or re.fullmatch(r"[0-9a-f]{64}", capability_fingerprint) is None:
            raise ValueError("CHART_STUDY_INPUT_INVALID")
        if capability_fingerprint != self._fingerprint:
            raise ValueError("CHART_STUDY_REGISTRATION_CHANGED")
        if (
            not isinstance(parameters, Mapping)
            or set(parameters) - {"period", "price_field"}
            or type(parameters.get("period", 20)) is not int
            or not 1 <= cast(int, parameters.get("period", 20)) <= MAX_PERIOD
            or type(parameters.get("price_field", "CLOSE")) is not str
            or parameters.get("price_field", "CLOSE") != "CLOSE"
        ):
            raise ValueError("CHART_STUDY_INPUT_INVALID")
        if not isinstance(inputs, Mapping) or set(inputs) != {"value"}:
            raise ValueError("CHART_STUDY_INPUT_INVALID")
        values = inputs["value"]
        if (
            not isinstance(values, (pa.Array, pa.ChunkedArray))
            or not pa.types.is_decimal128(values.type)
            or values.type.scale < 0
            or values.type.scale > 18
            or not 1 <= len(values) <= MAX_INPUT_ROWS
            or values.null_count
            or isinstance(values, pa.ChunkedArray)
            and values.num_chunks > MAX_INPUT_ROWS
        ):
            raise ValueError("CHART_STUDY_INPUT_INVALID")
        resolver = self._admission.registration.definition_resolver
        if resolver is None:
            raise ValueError("CHART_STUDY_UNAVAILABLE")
        definition = resolver.resolve(parameters, {})
        _require_sma_definition(definition, self._admission.registration.type_definition, parameters)
        backend = cast(OnlyResearchReadinessCalculationBackend, self._admission.registration.provider)
        with localcontext(only_decimal_context(only_chart_sma_effective_numeric(definition.numeric))):
            result = backend.execute_with_readiness(definition, inputs)
            outputs = only_validate_research_outputs(definition, result.outputs, len(values))
            only_validate_research_output_readiness(definition, outputs, result.readiness, row_count=len(values))
            output = outputs["value"]
            if output.type != pa.decimal128(38, 12) or output.null_count:
                raise ValueError("CHART_STUDY_OUTPUT_INVALID")
            evidence = result.readiness["value"]
            if any(state.as_py() not in {"PARTIAL", "READY"} for state in evidence.states):
                raise ValueError("CHART_STUDY_OUTPUT_INVALID")
            self._require_current()
            return OnlyResearchCalculationBackendExecutionV2(outputs, MappingProxyType(dict(result.readiness)))


def _require_sma_definition(
    definition: OnlyCalculationDefinition, descriptor: OnlyCalculationTypeDefinition, parameters: Mapping[str, object]
) -> None:
    expected_parameters = descriptor.parameters.normalize(parameters)
    if (
        OnlyCalculationTypeReference(definition.kind, definition.type_id, definition.semantic_version) != SMA_REFERENCE
        or set(definition.parameters) != {"period", "price_field"}
        or definition.parameters["price_field"] != "CLOSE"
        or tuple(item.name for item in definition.inputs) != ("value",)
        or tuple(item.name for item in definition.outputs) != ("value",)
        or definition.input_bindings["value"].source != "bar.close"
        or definition.missing_values is not OnlyMissingValuePolicy.FAIL
        or definition.timestamp is not OnlyTimestampSemantic.EVENT_TIME
        or definition.extensions
        or dict(definition.parameters) != dict(expected_parameters)
        or definition.inputs != descriptor.inputs
        or definition.outputs != descriptor.outputs
        or definition.numeric != descriptor.numeric
        or definition.input_bindings != {"value": OnlyCalculationReference(None, "value", "bar.close")}
        or definition.warmup
        != OnlyWarmupDefinition(
            int(str(definition.parameters["period"])),
            "samples >= minimum_observations",
            OnlyPreReadyOutput.PARTIAL,
            "PARTIAL_WINDOW",
        )
    ):
        raise ValueError("CHART_STUDY_UNAVAILABLE")
    only_chart_sma_effective_numeric(definition.numeric)


def _require_sma_registration(registration: OnlyCalculationBackendRegistration) -> None:
    descriptor = registration.type_definition
    if (
        descriptor.kind is not SMA_REFERENCE.kind
        or descriptor.type_id != SMA_REFERENCE.type_id
        or descriptor.semantic_version != SMA_REFERENCE.semantic_version
        or descriptor.execution_shape is not OnlyFactorKind.TIME_SERIES
        or descriptor.missing_values is not OnlyMissingValuePolicy.FAIL
        or descriptor.timestamp is not OnlyTimestampSemantic.EVENT_TIME
        or descriptor.inputs != (OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL),)
        or descriptor.outputs != (OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, True),)
        or registration.backend is not OnlyCalculationBackendKind.RESEARCH
    ):
        raise ValueError("CHART_STUDY_UNAVAILABLE")
    manifest = registration.implementation_manifest
    required = (
        only_decimal_execution_semantic_dependency(),
        only_chart_sma_numeric_dependency(),
        only_chart_study_invocation_dependency(),
        only_python_stdlib_semantic_dependency("decimal"),
        only_distribution_semantic_dependency("pyarrow"),
    )
    if manifest is None or set(manifest.semantic_dependencies) != set(required):
        raise ValueError("CHART_STUDY_DEPENDENCY_UNAVAILABLE")
    if (
        registration.readiness_contract_versions != (1,)
        or not isinstance(registration.provider, OnlyResearchReadinessCalculationBackend)
        or registration.definition_resolver is None
        or getattr(registration.definition_resolver, "type_definition", None) is not descriptor
        or not isinstance(registration.provider, OnlyChartNumericBindingVerifier)
        or vars(registration.provider)
        or {item.relative_path for item in manifest.resources} != {"registration.py", "research.py", "provider.py"}
    ):
        raise ValueError("CHART_STUDY_UNAVAILABLE")
    only_chart_sma_effective_numeric(descriptor.numeric)
    only_require_installed_implementation(manifest, registration.provider)
    cast(OnlyChartNumericBindingVerifier, registration.provider).require_chart_numeric_binding(descriptor.numeric)
