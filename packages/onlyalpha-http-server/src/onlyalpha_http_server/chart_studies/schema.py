"""Single versioned Chart Query transport schema; no uploaded market/numeric facts."""

from __future__ import annotations

from typing import Annotated, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from onlyalpha.application.chart_study_numeric import OnlyChartStudySmaAdmission
from onlyalpha.application.chart_study_product_query import OnlyChartStudyProjectionV1, OnlyChartStudyRequestV1
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

from ..market_data.schema import (
    MarketDataBarSemanticDto,
    MarketDataBarWindowDto,
    MarketDataCoverageDto,
    MarketDataRevisionEvidenceDto,
    MarketDataSourceReferenceDto,
    MarketDataSourceSelectionDto,
)

Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Nanoseconds = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]
Text = Annotated[str, Field(min_length=1, max_length=256)]


class _ChartDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def exact_literals(cls, value: object) -> object:
        # Pydantic's strict mode does not make Literal[1]/Literal[False] type-exact.
        if isinstance(value, dict):
            for name, field in cls.model_fields.items():
                if name in value and get_origin(field.annotation) is Literal:
                    options = get_args(field.annotation)
                    if not any(type(value[name]) is type(option) and value[name] == option for option in options):
                        raise ValueError("CHART_STUDY_REQUEST_INVALID")
        return value


class ChartStudyErrorDto(_ChartDto):
    phase: Literal["QUERY"]
    code: Text
    detail: Text


class ChartStudyErrorEnvelopeDto(_ChartDto):
    schema_version: Literal[1]
    error: ChartStudyErrorDto


class ChartStudySourceReferenceDto(MarketDataSourceReferenceDto):
    integration_id: Text
    expected_type_id: Text


class ChartStudyWindowDto(_ChartDto):
    anchor_kind: Literal["BEFORE_TIME"]
    before_ns: Nanoseconds
    target_bar_count: int = Field(ge=1, le=2000)

    @field_validator("before_ns")
    @classmethod
    def signed_time(cls, value: str) -> str:
        if int(value) > 9_223_372_036_854_775_807:
            raise ValueError("CHART_STUDY_REQUEST_INVALID")
        return value


class ChartStudyIntegerDto(_ChartDto):
    type: Literal["INTEGER"]
    value: int = Field(ge=1, le=10000)


class ChartStudyCloseDto(_ChartDto):
    type: Literal["STRING"]
    value: Literal["CLOSE"]


class ChartStudyParametersDto(_ChartDto):
    period: ChartStudyIntegerDto
    price_field: ChartStudyCloseDto


class ChartStudyCalculationRequestDto(_ChartDto):
    kind: Literal["INDICATOR"]
    type_id: Literal["onlyalpha.indicator.sma"]
    semantic_version: Literal["1"]
    typed_parameters: ChartStudyParametersDto
    output_members: list[Literal["value"]] = Field(min_length=1, max_length=1)
    expected_descriptor_fingerprint: Fingerprint
    expected_implementation_fingerprint: Fingerprint
    expected_capability_projection_fingerprint: Fingerprint


class ChartStudyEvaluateRequestDto(_ChartDto):
    schema_version: Literal[1]
    source_reference: ChartStudySourceReferenceDto
    instrument_id: Text
    bar_semantic: MarketDataBarSemanticDto
    window: ChartStudyWindowDto
    expected_history_projection_fingerprint: Fingerprint
    calculation: ChartStudyCalculationRequestDto
    include_unclosed_preview: Literal[False]

    @field_validator("bar_semantic", mode="before")
    @classmethod
    def exact_semantic_versions(cls, value: object) -> object:
        if isinstance(value, dict):
            formation = value.get("formation")
            if (
                type(value.get("schema_version")) is not int
                or not isinstance(formation, dict)
                or type(formation.get("schema_version")) is not int
            ):
                raise ValueError("CHART_STUDY_REQUEST_INVALID")
        return value

    def to_model(self) -> OnlyChartStudyRequestV1:
        calculation = self.calculation
        return OnlyChartStudyRequestV1(
            self.source_reference.to_model(),
            self.instrument_id,
            self.bar_semantic.to_model(),
            int(self.window.before_ns),
            self.window.target_bar_count,
            calculation.typed_parameters.period.value,
            self.expected_history_projection_fingerprint,
            calculation.expected_descriptor_fingerprint,
            calculation.expected_implementation_fingerprint,
            calculation.expected_capability_projection_fingerprint,
        )


class ChartStudyNumericDto(_ChartDto):
    representation: Literal["DECIMAL"]
    precision: Literal[28]
    output_quantum: Literal["0.000000000001"]
    rounding: Literal["CONTEXT"]


class ChartStudyPortDto(_ChartDto):
    name: Literal["value"]
    data_type: Literal["DECIMAL"]
    nullable: bool
    dimensions: list[Literal["TIME"]] = Field(min_length=1, max_length=1)
    semantic_type: Literal["NUMERIC_SERIES"]
    unit: None


class ChartStudyParameterDescriptorDto(_ChartDto):
    name: Literal["period", "price_field"]
    parameter_type: Literal["INTEGER", "STRING"]
    required: bool
    default: int | str
    minimum: int | None
    maximum: int | None
    enum_values: list[int | str] = Field(max_length=2)
    uppercase: bool


class ChartStudySemanticBoundsDto(_ChartDto):
    value: None


class ChartStudyDescriptorDto(_ChartDto):
    kind: Literal["INDICATOR"]
    type_id: Literal["onlyalpha.indicator.sma"]
    semantic_version: Literal["1"]
    parameters: list[ChartStudyParameterDescriptorDto] = Field(min_length=2, max_length=2)
    inputs: list[ChartStudyPortDto] = Field(min_length=1, max_length=1)
    outputs: list[ChartStudyPortDto] = Field(min_length=1, max_length=1)
    missing_values: Literal["FAIL"]
    timestamp: Literal["EVENT_TIME"]
    numeric: ChartStudyNumericDto
    factor_kind: None
    execution_shape: Literal["TIME_SERIES"]
    semantic_bounds: ChartStudySemanticBoundsDto


class ChartStudyTypeReferenceDto(_ChartDto):
    kind: Literal["INDICATOR"]
    type_id: Literal["onlyalpha.indicator.sma"]
    semantic_version: Literal["1"]


class ChartStudyResourceDto(_ChartDto):
    relative_path: Text
    byte_sha256: Fingerprint


class ChartStudyDependencyDto(_ChartDto):
    dependency_id: Text
    semantic_version: Text
    artifact_fingerprint: Fingerprint | None


class ChartStudyManifestDto(_ChartDto):
    schema_version: Literal[1]
    calculation_type_reference: ChartStudyTypeReferenceDto
    backend_kind: Literal["RESEARCH"]
    entrypoint_identity: Text
    resources: list[ChartStudyResourceDto] = Field(min_length=1, max_length=32)
    semantic_dependencies: list[ChartStudyDependencyDto] = Field(min_length=1, max_length=8)
    implementation_bundle_fingerprint: Fingerprint
    implementation_fingerprint: Fingerprint


class ChartStudyDistributionDto(_ChartDto):
    kind: Literal["DISTRIBUTION"]
    distribution_name: Text
    distribution_version: Text


class ChartStudyProviderManifestDto(_ChartDto):
    schema_version: Literal[1]
    provider_id: Text
    provider_version: Text
    kind: Literal["INDICATOR"]
    source: ChartStudyDistributionDto


class ChartStudyDecimalPolicyDto(_ChartDto):
    domain: Literal["onlyalpha.decimal.execution-policy"]
    policy_id: Literal["onlyalpha.decimal.execution"]
    semantic_version: Literal["1"]
    emin: Literal[-999999]
    emax: Literal[999999]
    capitals: Literal[1]
    clamp: Literal[0]
    entry_flags: Literal["CLEAR"]
    trapped_signals: list[Literal["DivisionByZero", "InvalidOperation", "Overflow"]] = Field(min_length=3, max_length=3)


class ChartStudyNumericBindingDto(_ChartDto):
    domain: Literal["onlyalpha.chart-study.decimal-binding"]
    schema_version: Literal[1]
    resolution_policy: Literal["CONTEXT_HALF_EVEN_V1"]
    declared_rounding: Literal["CONTEXT"]
    effective_rounding: Literal["ROUND_HALF_EVEN"]
    representation: Literal["DECIMAL"]
    precision: Literal[28]
    output_quantum: Literal["0.000000000001"]
    core_policy: ChartStudyDecimalPolicyDto
    core_policy_fingerprint: Fingerprint


class ChartStudyLimitsDto(_ChartDto):
    max_input_rows: Literal[2000]
    max_period: Literal[10000]
    max_concurrent_invocations: Literal[1]


class ChartStudyCapabilityProjectionDto(_ChartDto):
    """Exact P2 complete hash payload, not a second capability identity."""

    domain: Literal["onlyalpha.chart-study.capability-projection"]
    schema_version: Literal[1]
    source_kind: Literal["CHART_STUDY_TRANSIENT"]
    authority: Literal["DISPLAY_ONLY"]
    publication_status: Literal["NOT_A_RESEARCH_RESULT"]
    descriptor: ChartStudyDescriptorDto
    backend: Literal["RESEARCH"]
    implementation: ChartStudyManifestDto
    invocation: ChartStudyManifestDto
    provider_manifest: ChartStudyProviderManifestDto
    provider_content_fingerprint: Fingerprint
    catalog_generation_fingerprint: Fingerprint
    readiness_contract_versions: list[Literal[1]] = Field(min_length=1, max_length=1)
    output_members: list[Literal["value"]] = Field(min_length=1, max_length=1)
    supported_shape: Literal["TIME_SERIES/CLOSED_HISTORY/CLOSE/value"]
    finite_initialization: Literal["PARTIAL_WINDOW_AT_EXPLICIT_FINITE_START"]
    limits: ChartStudyLimitsDto
    numeric_binding: ChartStudyNumericBindingDto


class ChartStudyCapabilityDto(_ChartDto):
    kind: Literal["INDICATOR"]
    type_id: Literal["onlyalpha.indicator.sma"]
    semantic_version: Literal["1"]
    descriptor: ChartStudyDescriptorDto
    descriptor_fingerprint: Fingerprint
    backend: Literal["RESEARCH"]
    implementation_fingerprint: Fingerprint
    provider_id: Text
    provider_version: Text
    provider_content_fingerprint: Fingerprint
    catalog_generation_fingerprint: Fingerprint
    readiness_contract_version: Literal[1]
    execution_shape: Literal["TIME_SERIES"]
    output_members: list[Literal["value"]] = Field(min_length=1, max_length=1)
    limits: ChartStudyLimitsDto
    numeric_execution_binding: ChartStudyNumericBindingDto
    invocation_implementation_fingerprint: Fingerprint
    capability_projection: ChartStudyCapabilityProjectionDto
    capability_projection_fingerprint: Fingerprint

    @classmethod
    def from_model(cls, admission: OnlyChartStudySmaAdmission) -> ChartStudyCapabilityDto:
        p = ChartStudyCapabilityProjectionDto.model_validate_json(only_canonical_json(admission.payload()))
        return cls(
            kind="INDICATOR",
            type_id="onlyalpha.indicator.sma",
            semantic_version="1",
            descriptor=p.descriptor,
            descriptor_fingerprint=only_canonical_fingerprint(admission.registration.type_definition.descriptor()),
            backend="RESEARCH",
            implementation_fingerprint=p.implementation.implementation_fingerprint,
            provider_id=p.provider_manifest.provider_id,
            provider_version=p.provider_manifest.provider_version,
            provider_content_fingerprint=p.provider_content_fingerprint,
            catalog_generation_fingerprint=p.catalog_generation_fingerprint,
            readiness_contract_version=1,
            execution_shape="TIME_SERIES",
            output_members=["value"],
            limits=p.limits,
            numeric_execution_binding=p.numeric_binding,
            invocation_implementation_fingerprint=p.invocation.implementation_fingerprint,
            capability_projection=p,
            capability_projection_fingerprint=admission.fingerprint,
        )


class ChartStudyCapabilitiesDto(_ChartDto):
    schema_version: Literal[1]
    capabilities: list[ChartStudyCapabilityDto] = Field(min_length=1, max_length=1)


class ChartStudyInputDto(_ChartDto):
    anchor_kind: Literal["BEFORE_TIME"]
    before_ns: Nanoseconds
    target_bar_count: int = Field(ge=1, le=2000)
    resolved_start_ns: Nanoseconds
    resolved_end_ns: Nanoseconds
    initialization: Literal["FINITE_WINDOW_START"]
    revision_evidence: list[MarketDataRevisionEvidenceDto] = Field(max_length=2000)
    history_projection_fingerprint: Fingerprint | None
    resolution_mode: Literal["PROVIDER_NATIVE"]
    resolution_plan_fingerprint: Fingerprint
    derived_projection_fingerprint: None
    aggregation_semantics_version: str | None
    calendar_fingerprint: Fingerprint
    resume_after_sequence: str | None
    resume_plan_fingerprint: Fingerprint | None


class ChartStudyOutputDto(_ChartDto):
    name: Literal["value"]
    data_type: Literal["DECIMAL"]
    nullable: Literal[True]
    unit: Literal["PRICE"]


class ChartStudyWarmupDto(_ChartDto):
    initialization: Literal["PARTIAL_WINDOW"]
    minimum_observations: int = Field(ge=1, le=10000)
    pre_ready_output: Literal["PARTIAL"]
    ready_condition: Literal["samples >= minimum_observations"]


class ChartStudyInputBindingDto(_ChartDto):
    source: Literal["bar.close"]
    node_fingerprint: None
    output_name: Literal["value"]


class ChartStudyInputBindingsDto(_ChartDto):
    value: ChartStudyInputBindingDto


class ChartStudyExtensionsDto(_ChartDto):
    pass


class ChartStudyDefinitionParametersDto(_ChartDto):
    period: int = Field(ge=1, le=10000)
    price_field: Literal["CLOSE"]


class ChartStudyDefinitionDto(_ChartDto):
    schema_version: Literal[2]
    kind: Literal["INDICATOR"]
    type_id: Literal["onlyalpha.indicator.sma"]
    semantic_version: Literal["1"]
    parameters: ChartStudyDefinitionParametersDto
    inputs: list[ChartStudyPortDto] = Field(min_length=1, max_length=1)
    outputs: list[ChartStudyPortDto] = Field(min_length=1, max_length=1)
    input_bindings: ChartStudyInputBindingsDto
    missing_values: Literal["FAIL"]
    timestamp: Literal["EVENT_TIME"]
    warmup: ChartStudyWarmupDto
    numeric: ChartStudyNumericDto
    factor_kind: None
    extensions: ChartStudyExtensionsDto


class ChartStudyCalculationDto(_ChartDto):
    kind: Literal["INDICATOR"]
    type_id: Literal["onlyalpha.indicator.sma"]
    semantic_version: Literal["1"]
    normalized_typed_parameters: ChartStudyParametersDto
    definition_fingerprint: Fingerprint
    normalized_definition: ChartStudyDefinitionDto
    descriptor_fingerprint: Fingerprint
    backend: Literal["RESEARCH"]
    implementation_fingerprint: Fingerprint
    provider_id: Text
    provider_version: Text
    provider_content_fingerprint: Fingerprint
    catalog_generation_fingerprint: Fingerprint
    capability_projection_fingerprint: Fingerprint
    numeric: ChartStudyNumericDto
    numeric_execution_binding: ChartStudyNumericBindingDto
    invocation_implementation_fingerprint: Fingerprint
    output_members: list[ChartStudyOutputDto] = Field(min_length=1, max_length=1)


class ChartStudyPointDto(_ChartDto):
    time_ns: Nanoseconds
    value: Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)\.[0-9]{12}$", max_length=64)] | None
    readiness: Literal["PARTIAL", "READY"]
    reason: Literal["NONE", "WARMUP_INCOMPLETE", "VALUE_UNDEFINED"]
    quality: Literal["CLOSED_COMPLETE"]
    closed: Literal[True]


class ChartStudySeriesDto(_ChartDto):
    output_name: Literal["value"]
    points: list[ChartStudyPointDto] = Field(min_length=1, max_length=2000)


class ChartStudyEvaluateDto(_ChartDto):
    schema_version: Literal[1]
    source_kind: Literal["CHART_STUDY_TRANSIENT"]
    authority: Literal["DISPLAY_ONLY"]
    publication_status: Literal["NOT_A_RESEARCH_RESULT"]
    source_selection: MarketDataSourceSelectionDto
    instrument_id: Text
    bar_semantic: MarketDataBarSemanticDto
    input: ChartStudyInputDto
    coverage: MarketDataCoverageDto
    query_status: Literal["DISPLAYABLE", "INPUT_INCOMPLETE"]
    calculation: ChartStudyCalculationDto
    series: list[ChartStudySeriesDto] = Field(max_length=1)

    @classmethod
    def from_model(cls, value: OnlyChartStudyProjectionV1) -> ChartStudyEvaluateDto:
        window = MarketDataBarWindowDto.from_model(value.window)
        capability = ChartStudyCapabilityDto.from_model(value.admission)
        definition = value.definition
        parameters = ChartStudyParametersDto.model_validate_json(
            only_canonical_json(
                {
                    "period": {"type": "INTEGER", "value": definition.parameters["period"]},
                    "price_field": {"type": "STRING", "value": definition.parameters["price_field"]},
                }
            )
        )
        if (
            window.requested_before_ns is None
            or window.resolution_mode != "PROVIDER_NATIVE"
            or window.resolution_plan_fingerprint is None
            or window.calendar_fingerprint is None
        ):
            raise ValueError("CHART_STUDY_SOURCE_UNAVAILABLE")
        fields = {
            name: getattr(capability, name)
            for name in (
                "kind",
                "type_id",
                "semantic_version",
                "descriptor_fingerprint",
                "backend",
                "implementation_fingerprint",
                "provider_id",
                "provider_version",
                "provider_content_fingerprint",
                "catalog_generation_fingerprint",
                "capability_projection_fingerprint",
                "numeric_execution_binding",
                "invocation_implementation_fingerprint",
            )
        }
        calculation = ChartStudyCalculationDto(
            **fields,
            normalized_typed_parameters=parameters,
            definition_fingerprint=definition.fingerprint,
            normalized_definition=ChartStudyDefinitionDto.model_validate_json(
                only_canonical_json(definition.semantic_payload())
            ),
            numeric=capability.descriptor.numeric,
            output_members=[ChartStudyOutputDto(name="value", data_type="DECIMAL", nullable=True, unit="PRICE")],
        )
        execution = value.execution
        series = []
        if execution is not None:
            readiness = execution.readiness["value"]
            points = [
                ChartStudyPointDto(
                    time_ns=str(bar.bar_start_ns),
                    value=None if number is None else format(number, "f"),
                    readiness=state,
                    reason=reason,
                    quality="CLOSED_COMPLETE",
                    closed=True,
                )
                for bar, number, state, reason in zip(
                    value.window.bars,
                    execution.outputs["value"].to_pylist(),
                    readiness.states.to_pylist(),
                    readiness.reasons.to_pylist(),
                    strict=True,
                )
            ]
            series = [ChartStudySeriesDto(output_name="value", points=points)]
        return cls(
            schema_version=1,
            source_kind="CHART_STUDY_TRANSIENT",
            authority="DISPLAY_ONLY",
            publication_status="NOT_A_RESEARCH_RESULT",
            source_selection=window.source_selection,
            instrument_id=window.instrument_id,
            bar_semantic=window.bar_semantic,
            input=ChartStudyInputDto(
                anchor_kind="BEFORE_TIME",
                before_ns=window.requested_before_ns,
                target_bar_count=window.requested_bar_count,
                resolved_start_ns=window.resolved_start_ns,
                resolved_end_ns=window.resolved_end_ns,
                initialization="FINITE_WINDOW_START",
                revision_evidence=list(window.revision_evidence),
                history_projection_fingerprint=window.history_projection_fingerprint,
                resolution_mode=window.resolution_mode,
                resolution_plan_fingerprint=window.resolution_plan_fingerprint,
                derived_projection_fingerprint=None,
                aggregation_semantics_version=window.aggregation_semantics_version,
                calendar_fingerprint=window.calendar_fingerprint,
                resume_after_sequence=window.resume_after_sequence,
                resume_plan_fingerprint=window.resume_plan_fingerprint,
            ),
            coverage=window.coverage,
            query_status="INPUT_INCOMPLETE" if execution is None else "DISPLAYABLE",
            calculation=calculation,
            series=series,
        )
