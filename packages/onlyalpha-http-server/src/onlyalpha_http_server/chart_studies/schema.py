"""Single versioned Chart Query transport schema; no uploaded market/numeric facts."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from onlyalpha.application.chart_study_numeric import OnlyChartStudyAdmission
from onlyalpha.application.chart_study_product_query import OnlyChartStudyProjectionV2, OnlyChartStudyRequestV2
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendExecutionV2

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
OutputName = Annotated[str, Field(min_length=1, max_length=128)]


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


class ChartStudyStringDto(_ChartDto):
    type: Literal["STRING"]
    value: Text


class ChartStudyDecimalDto(_ChartDto):
    type: Literal["DECIMAL"]
    value: Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$", max_length=64)]

    @field_validator("value")
    @classmethod
    def canonical_decimal(cls, value: str) -> str:
        number = Decimal(value)
        if not number.is_finite() or (number == 0 and value.startswith("-")):
            raise ValueError("CHART_STUDY_REQUEST_INVALID")
        return value


class ChartStudyBooleanDto(_ChartDto):
    type: Literal["BOOLEAN"]
    value: bool


ChartStudyParameter = ChartStudyIntegerDto | ChartStudyStringDto | ChartStudyDecimalDto | ChartStudyBooleanDto


class ChartStudyCalculationRequestDto(_ChartDto):
    kind: Literal["INDICATOR"]
    type_id: Text
    semantic_version: Text
    typed_parameters: dict[Text, ChartStudyParameter] = Field(max_length=16)
    output_members: list[OutputName] = Field(min_length=1, max_length=8, json_schema_extra={"uniqueItems": True})

    @field_validator("output_members")
    @classmethod
    def unique_outputs(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("CHART_STUDY_REQUEST_INVALID")
        return value

    expected_descriptor_fingerprint: Fingerprint
    expected_implementation_fingerprint: Fingerprint
    expected_capability_projection_fingerprint: Fingerprint


class ChartStudyEvaluateRequestDto(_ChartDto):
    schema_version: Literal[2]
    source_reference: ChartStudySourceReferenceDto
    instrument_id: Text
    bar_semantic: MarketDataBarSemanticDto
    window: ChartStudyWindowDto
    expected_history_projection_fingerprint: Fingerprint
    calculation: ChartStudyCalculationRequestDto
    include_unclosed_preview: bool
    preview_stream_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")] | None

    @model_validator(mode="after")
    def preview_binding(self) -> ChartStudyEvaluateRequestDto:
        if self.include_unclosed_preview != (self.preview_stream_id is not None):
            raise ValueError("CHART_STUDY_REQUEST_INVALID")
        return self

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

    def to_model(self) -> OnlyChartStudyRequestV2:
        calculation = self.calculation
        return OnlyChartStudyRequestV2(
            reference=self.source_reference.to_model(),
            instrument_id=self.instrument_id,
            bar_semantic=self.bar_semantic.to_model(),
            before_ns=int(self.window.before_ns),
            target_bar_count=self.window.target_bar_count,
            type_id=calculation.type_id,
            semantic_version=calculation.semantic_version,
            parameters={
                name: Decimal(item.value) if isinstance(item, ChartStudyDecimalDto) else item.value
                for name, item in calculation.typed_parameters.items()
            },
            output_members=tuple(calculation.output_members),
            expected_history_projection_fingerprint=self.expected_history_projection_fingerprint,
            expected_descriptor_fingerprint=calculation.expected_descriptor_fingerprint,
            expected_implementation_fingerprint=calculation.expected_implementation_fingerprint,
            expected_capability_projection_fingerprint=calculation.expected_capability_projection_fingerprint,
            include_unclosed_preview=self.include_unclosed_preview,
            preview_stream_id=self.preview_stream_id,
        )


class ChartStudyNumericDto(_ChartDto):
    representation: Literal["DECIMAL"]
    precision: Literal[28]
    output_quantum: Literal["0.000000000001"]
    rounding: Literal["CONTEXT", "ROUND_HALF_EVEN"]


class ChartStudyPortDto(_ChartDto):
    name: Text
    data_type: Literal["DECIMAL", "INTEGER", "STRING", "BOOLEAN"]
    nullable: bool
    dimensions: list[Literal["TIME"]] = Field(min_length=1, max_length=1)
    semantic_type: Text
    unit: Text | None


class ChartStudyParameterDescriptorDto(_ChartDto):
    name: Text
    parameter_type: Literal["INTEGER", "STRING", "DECIMAL", "BOOLEAN"]
    required: bool
    default: int | str | bool | None
    minimum: int | str | None
    maximum: int | str | None
    enum_values: list[int | str | bool | None] = Field(max_length=32)
    uppercase: bool


class ChartStudyDescriptorDto(_ChartDto):
    kind: Literal["INDICATOR"]
    type_id: Text
    semantic_version: Text
    parameters: list[ChartStudyParameterDescriptorDto] = Field(max_length=16)
    inputs: list[ChartStudyPortDto] = Field(min_length=1, max_length=16)
    outputs: list[ChartStudyPortDto] = Field(min_length=1, max_length=16)
    missing_values: Literal["FAIL", "PROPAGATE", "SKIP", "RESET"]
    timestamp: Literal["EVENT_TIME"]
    numeric: ChartStudyNumericDto
    factor_kind: None
    execution_shape: Literal["TIME_SERIES"]
    semantic_bounds: dict[Text, list[str] | None]


class ChartStudyTypeReferenceDto(_ChartDto):
    kind: Literal["INDICATOR"]
    type_id: Text
    semantic_version: Text


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
    declared_rounding: Literal["CONTEXT", "ROUND_HALF_EVEN"]
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


class ChartStudyInputSupportDto(_ChartDto):
    instrument_policy: Literal["EXACT_SOURCE_CATALOG"]
    resolution_mode: Literal["PROVIDER_NATIVE"]
    bar_formation: Literal["FIXED_DURATION"]
    alignment: Literal["UTC_24X7"]
    closed_only: Literal[False]
    preview_mode: Literal["OWNING_STREAM_SNAPSHOT"]
    coverage_policy: Literal["COMPLETE_VERIFIED_WINDOW"]


class ChartStudyPresentationSeriesDto(_ChartDto):
    output_name: Text
    label: Text
    kind: Literal["LINE", "HISTOGRAM"]
    unit: Literal["PRICE", "RATIO", "VOLUME", "SCALAR"]
    color: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
    default_visible: bool


class ChartStudyPresentationDto(_ChartDto):
    display_name: Text
    category: Text
    default_parameters: dict[Text, int | str | bool] = Field(max_length=16)
    series: list[ChartStudyPresentationSeriesDto] = Field(min_length=1, max_length=16)
    placement: Literal["PRICE_OVERLAY", "SEPARATE_PANE"]
    fill: Annotated[list[Text], Field(min_length=2, max_length=2)] | None
    preview_supported: bool
    default_variant: bool


class ChartStudyCapabilityProjectionDto(_ChartDto):
    """Exact installed admission hash payload, not a second capability identity."""

    domain: Literal["onlyalpha.chart-study.capability-projection"]
    schema_version: Literal[2]
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
    output_members: list[Text] = Field(min_length=1, max_length=16)
    supported_shape: Literal["TIME_SERIES/BAR_FIELDS"]
    input_support: ChartStudyInputSupportDto
    finite_initialization: Literal["PARTIAL_WINDOW_AT_EXPLICIT_FINITE_START"]
    limits: ChartStudyLimitsDto
    numeric_binding: ChartStudyNumericBindingDto
    presentation: ChartStudyPresentationDto


class ChartStudyCapabilityDto(_ChartDto):
    kind: Literal["INDICATOR"]
    type_id: Text
    semantic_version: Text
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
    output_members: list[Text] = Field(min_length=1, max_length=16)
    limits: ChartStudyLimitsDto
    numeric_execution_binding: ChartStudyNumericBindingDto
    invocation_implementation_fingerprint: Fingerprint
    presentation: ChartStudyPresentationDto
    capability_projection: ChartStudyCapabilityProjectionDto
    capability_projection_fingerprint: Fingerprint

    @classmethod
    def from_model(cls, admission: OnlyChartStudyAdmission) -> ChartStudyCapabilityDto:
        p = ChartStudyCapabilityProjectionDto.model_validate_json(only_canonical_json(admission.payload()))
        return cls(
            kind="INDICATOR",
            type_id=p.descriptor.type_id,
            semantic_version=p.descriptor.semantic_version,
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
            output_members=p.output_members,
            presentation=p.presentation,
            limits=p.limits,
            numeric_execution_binding=p.numeric_binding,
            invocation_implementation_fingerprint=p.invocation.implementation_fingerprint,
            capability_projection=p,
            capability_projection_fingerprint=admission.fingerprint,
        )


class ChartStudyCapabilitiesDto(_ChartDto):
    schema_version: Literal[2]
    capabilities: list[ChartStudyCapabilityDto] = Field(min_length=1, max_length=64)


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
    name: Text
    data_type: Literal["DECIMAL"]
    nullable: bool
    unit: Literal["PRICE", "RATIO", "VOLUME", "SCALAR"]


class ChartStudyWarmupDto(_ChartDto):
    initialization: Text
    minimum_observations: int = Field(ge=1, le=10000)
    pre_ready_output: Literal["PARTIAL", "NULL"]
    ready_condition: Text


class ChartStudyInputBindingDto(_ChartDto):
    source: Literal["bar.open", "bar.high", "bar.low", "bar.close", "bar.volume", "bar.start_ns"]
    node_fingerprint: None
    output_name: Text


class ChartStudyExtensionsDto(_ChartDto):
    pass


class ChartStudyDefinitionDto(_ChartDto):
    schema_version: Literal[2]
    kind: Literal["INDICATOR"]
    type_id: Text
    semantic_version: Text
    parameters: dict[Text, int | str | bool | None] = Field(max_length=16)
    inputs: list[ChartStudyPortDto] = Field(min_length=1, max_length=16)
    outputs: list[ChartStudyPortDto] = Field(min_length=1, max_length=16)
    input_bindings: dict[Text, ChartStudyInputBindingDto] = Field(max_length=16)
    missing_values: Literal["FAIL", "PROPAGATE", "SKIP", "RESET"]
    timestamp: Literal["EVENT_TIME"]
    warmup: ChartStudyWarmupDto
    numeric: ChartStudyNumericDto
    factor_kind: None
    extensions: ChartStudyExtensionsDto


class ChartStudyCalculationDto(_ChartDto):
    kind: Literal["INDICATOR"]
    type_id: Text
    semantic_version: Text
    normalized_typed_parameters: dict[Text, ChartStudyParameter] = Field(max_length=16)
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
    output_members: list[ChartStudyOutputDto] = Field(min_length=1, max_length=16)


class _ChartStudyPointValueDto(_ChartDto):
    time_ns: Nanoseconds
    value: Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)\.[0-9]{12}$", max_length=64)] | None
    readiness: Literal["PARTIAL", "READY", "UNAVAILABLE"]
    reason: Literal["NONE", "WARMUP_INCOMPLETE", "VALUE_UNDEFINED", "INPUT_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE"]


class ChartStudyPointDto(_ChartStudyPointValueDto):
    quality: Literal["CLOSED_COMPLETE"]
    closed: Literal[True]


class ChartStudySeriesDto(_ChartDto):
    output_name: Text
    points: list[ChartStudyPointDto] = Field(min_length=1, max_length=2000)


class ChartStudyPreviewPointDto(_ChartStudyPointValueDto):
    quality: Literal["PREVIEW_UNCLOSED"]
    closed: Literal[False]


class ChartStudyPreviewSeriesDto(_ChartDto):
    output_name: Text
    point: ChartStudyPreviewPointDto


class ChartStudyPreviewDto(_ChartDto):
    source_kind: Literal["PREVIEW_UNCLOSED"]
    stream_id: Text
    revision_fingerprint: Fingerprint
    bar_start_ns: Nanoseconds
    bar_end_ns: Nanoseconds
    series: list[ChartStudyPreviewSeriesDto] = Field(min_length=1, max_length=16)


class ChartStudyEvaluateDto(_ChartDto):
    schema_version: Literal[2]
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
    series: list[ChartStudySeriesDto] = Field(max_length=16)
    preview: ChartStudyPreviewDto | None

    @classmethod
    def from_model(cls, value: OnlyChartStudyProjectionV2) -> ChartStudyEvaluateDto:
        window = MarketDataBarWindowDto.from_model(value.window)
        capability = ChartStudyCapabilityDto.from_model(value.admission)
        definition = value.definition
        parameter_types = {item.name: item.parameter_type for item in capability.descriptor.parameters}
        parameters = {
            name: {"type": parameter_types[name], "value": format(item, "f") if isinstance(item, Decimal) else item}
            for name, item in definition.parameters.items()
        }
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
            normalized_typed_parameters=TypeAdapter(dict[str, ChartStudyParameter]).validate_python(parameters),
            definition_fingerprint=definition.fingerprint,
            normalized_definition=ChartStudyDefinitionDto.model_validate_json(
                only_canonical_json(definition.semantic_payload())
            ),
            numeric=capability.descriptor.numeric,
            output_members=[
                ChartStudyOutputDto(
                    name=name,
                    data_type="DECIMAL",
                    nullable=next(p.nullable for p in capability.descriptor.outputs if p.name == name),
                    unit=next(p.unit for p in capability.presentation.series if p.output_name == name),
                )
                for name in value.output_members
            ],
        )

        def points(
            execution: OnlyResearchCalculationBackendExecutionV2, name: str, times: list[int], preview: bool = False
        ) -> list[dict[str, object]]:
            readiness = execution.readiness[name]
            return [
                dict(
                    time_ns=str(time),
                    value=None if number is None else format(number, "f"),
                    readiness=state,
                    reason=reason,
                    quality="PREVIEW_UNCLOSED" if preview else "CLOSED_COMPLETE",
                    closed=not preview,
                )
                for time, number, state, reason in zip(
                    times,
                    execution.outputs[name].to_pylist(),
                    readiness.states.to_pylist(),
                    readiness.reasons.to_pylist(),
                    strict=True,
                )
            ]

        series = (
            []
            if value.execution is None
            else [
                ChartStudySeriesDto(
                    output_name=name,
                    points=[
                        ChartStudyPointDto.model_validate(point)
                        for point in points(value.execution, name, [bar.bar_start_ns for bar in value.window.bars])
                    ],
                )
                for name in value.output_members
            ]
        )
        preview = None
        if value.preview is not None:
            row = value.preview
            preview = ChartStudyPreviewDto(
                source_kind="PREVIEW_UNCLOSED",
                stream_id=row.stream_id,
                revision_fingerprint=row.revision_fingerprint,
                bar_start_ns=str(row.bar_start_ns),
                bar_end_ns=str(row.bar_end_ns),
                series=[
                    ChartStudyPreviewSeriesDto(
                        output_name=name,
                        point=ChartStudyPreviewPointDto.model_validate(
                            points(row.execution, name, [row.bar_start_ns], True)[0]
                        ),
                    )
                    for name in value.output_members
                ],
            )
        return cls(
            schema_version=2,
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
            query_status="INPUT_INCOMPLETE" if value.execution is None else "DISPLAYABLE",
            calculation=calculation,
            series=series,
            preview=preview,
        )
