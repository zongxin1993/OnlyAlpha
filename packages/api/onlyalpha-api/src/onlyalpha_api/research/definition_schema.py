"""Strict transport and projection DTOs for Research discovery and Definition resolution."""

from __future__ import annotations

from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictInt, StrictStr

from onlyalpha.calculation import (
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyCalculationScalar,
    OnlyCalculationTypeDefinition,
    only_calculation_scalar_to_dict,
)
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType
from onlyalpha.research.definition.model import OnlyResearchDefinition, OnlyResearchUniverseKind
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolution
from onlyalpha.research.evaluation.capability import OnlyResearchStatisticsCapability
from onlyalpha.research.evaluation.definition import (
    OnlyResearchPairingPolicy,
    OnlyResearchRankTieMethod,
    OnlyResearchStatisticsMethod,
    OnlyResearchUniversePolicy,
    OnlyResearchWeighting,
)

from .discovery import ResearchUniverseDiscovery
from .schema import RESEARCH_API_SCHEMA_VERSION


class _StrictDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ResearchScalarDto(_StrictDto):
    type: Literal["NULL", "BOOLEAN", "INTEGER", "DECIMAL", "STRING"]
    value: StrictBool | StrictInt | StrictStr | None

    @classmethod
    def from_scalar(cls, value: OnlyCalculationScalar) -> ResearchScalarDto:
        return cls.model_validate(only_calculation_scalar_to_dict(value))


class ResearchCalculationTypeReferenceDto(_StrictDto):
    kind: OnlyCalculationKind
    type_id: str
    semantic_version: str


class ResearchParameterDefinitionDto(_StrictDto):
    name: str
    type: str
    required: bool
    default: ResearchScalarDto
    minimum: ResearchScalarDto | None
    maximum: ResearchScalarDto | None
    enum_values: tuple[ResearchScalarDto, ...]
    uppercase: bool


class ResearchInputDefinitionDto(_StrictDto):
    name: str
    data_type: str
    nullable: bool
    semantic_type: str
    dimensions: tuple[str, ...]
    unit: str | None


class ResearchOutputDefinitionDto(ResearchInputDefinitionDto):
    pass


class ResearchCalculationCatalogItemDto(_StrictDto):
    kind: str
    type_reference: ResearchCalculationTypeReferenceDto
    parameters: tuple[ResearchParameterDefinitionDto, ...]
    inputs: tuple[ResearchInputDefinitionDto, ...]
    outputs: tuple[ResearchOutputDefinitionDto, ...]
    parameter_sweep_allowed: bool

    @classmethod
    def from_model(cls, value: OnlyCalculationTypeDefinition) -> ResearchCalculationCatalogItemDto:
        def input_port(item: object) -> ResearchInputDefinitionDto:
            return ResearchInputDefinitionDto(
                name=item.name,  # type: ignore[attr-defined]
                data_type=item.data_type.value,  # type: ignore[attr-defined]
                nullable=item.nullable,  # type: ignore[attr-defined]
                semantic_type=item.semantic_type,  # type: ignore[attr-defined]
                dimensions=item.dimensions,  # type: ignore[attr-defined]
                unit=item.unit,  # type: ignore[attr-defined]
            )

        return cls(
            kind=value.kind.value,
            type_reference=ResearchCalculationTypeReferenceDto(
                kind=value.kind, type_id=value.type_id, semantic_version=value.semantic_version
            ),
            parameters=tuple(
                ResearchParameterDefinitionDto(
                    name=item.name,
                    type=item.parameter_type.value,
                    required=item.required,
                    default=ResearchScalarDto.from_scalar(item.default),
                    minimum=None if item.minimum is None else ResearchScalarDto.from_scalar(item.minimum),
                    maximum=None if item.maximum is None else ResearchScalarDto.from_scalar(item.maximum),
                    enum_values=tuple(ResearchScalarDto.from_scalar(candidate) for candidate in item.enum_values),
                    uppercase=item.uppercase,
                )
                for item in value.parameters.fields
            ),
            inputs=tuple(input_port(item) for item in value.inputs),
            outputs=tuple(ResearchOutputDefinitionDto(**input_port(item).model_dump()) for item in value.outputs),
            parameter_sweep_allowed=value.kind is not OnlyCalculationKind.TARGET,
        )


class ResearchCalculationCatalogDto(_StrictDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    calculations: tuple[ResearchCalculationCatalogItemDto, ...]


class ResearchDatasetFieldDto(_StrictDto):
    source: str
    field_name: str
    data_type: str
    semantic_roles: tuple[str, ...]
    dimensions: tuple[str, ...]
    unit: str | None


class ResearchDatasetFieldCatalogDto(_StrictDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    dataset_fields: tuple[ResearchDatasetFieldDto, ...]


class ResearchRegisteredUniverseDto(_StrictDto):
    registered_id: str
    kind: str
    display_metadata: dict[str, JsonValue]


class ResearchUniverseCatalogDto(_StrictDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    selection_kinds: tuple[str, ...]
    registered_universes: tuple[ResearchRegisteredUniverseDto, ...]

    @classmethod
    def from_model(cls, value: ResearchUniverseDiscovery) -> ResearchUniverseCatalogDto:
        return cls(
            selection_kinds=tuple(item.value for item in value.selection_kinds),
            registered_universes=tuple(
                ResearchRegisteredUniverseDto(
                    registered_id=item.registered_id,
                    kind=item.kind.value,
                    display_metadata=dict(item.display_metadata),  # type: ignore[arg-type]
                )
                for item in value.registered_universes
            ),
        )


class ResearchStatisticsCapabilityDto(_StrictDto):
    statistic_type: str
    variable_kinds: tuple[str, ...]
    variable_semantic_roles: tuple[str, ...]
    target_semantic_roles: tuple[str, ...]
    target_required: bool
    executable: bool

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticsCapability) -> ResearchStatisticsCapabilityDto:
        return cls(
            statistic_type=value.method.value,
            variable_kinds=tuple(item.value for item in value.variable_kinds),
            variable_semantic_roles=value.variable_semantic_types,
            target_semantic_roles=value.target_semantic_types,
            target_required=value.target_required,
            executable=value.executable,
        )


class ResearchStatisticsCapabilityCatalogDto(_StrictDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    statistics: tuple[ResearchStatisticsCapabilityDto, ...]


class ResearchUniverseSelectionDto(_StrictDto):
    kind: OnlyResearchUniverseKind
    instrument_ids: tuple[str, ...]
    registered_id: str | None


class ResearchBarSpecificationDto(_StrictDto):
    step: StrictInt
    aggregation: OnlyBarAggregation
    price_type: OnlyPriceType


class ResearchDatasetSelectionDto(_StrictDto):
    universe: ResearchUniverseSelectionDto
    bar_specification: ResearchBarSpecificationDto
    aggregation_source: OnlyAggregationSource
    start: str
    end: str
    adjustment_type: OnlyAdjustmentType
    adjustment_reference: str | None


class ResearchDatasetFieldRefDto(_StrictDto):
    kind: Literal["DATASET_FIELD"]
    field_name: str


class ResearchVariableRefDto(_StrictDto):
    kind: Literal["VARIABLE"]
    instance_key: str
    output_name: str


class ResearchTypedLiteralDto(_StrictDto):
    kind: Literal["LITERAL"]
    data_type: OnlyCalculationDataType
    value: ResearchScalarDto


ResearchOperandDto = Annotated[
    ResearchDatasetFieldRefDto | ResearchVariableRefDto | ResearchTypedLiteralDto,
    Field(discriminator="kind"),
]


class ResearchComparisonDto(_StrictDto):
    kind: Literal["COMPARISON"]
    operator: Literal["==", "!=", "<", "<=", ">", ">="]
    left: ResearchOperandDto
    right: ResearchOperandDto


class ResearchNotDto(_StrictDto):
    kind: Literal["NOT"]
    operand: ResearchExpressionDto


class ResearchAndDto(_StrictDto):
    kind: Literal["AND"]
    operands: tuple[ResearchExpressionDto, ...]


class ResearchOrDto(_StrictDto):
    kind: Literal["OR"]
    operands: tuple[ResearchExpressionDto, ...]


ResearchExpressionDto = Annotated[
    ResearchComparisonDto | ResearchNotDto | ResearchAndDto | ResearchOrDto,
    Field(discriminator="kind"),
]


class ResearchFixedParameterDto(_StrictDto):
    kind: Literal["FIXED"]
    value: ResearchScalarDto


class ResearchSweepParameterDto(_StrictDto):
    kind: Literal["SWEEP"]
    values: tuple[ResearchScalarDto, ...]


ResearchParameterBindingDto = Annotated[
    ResearchFixedParameterDto | ResearchSweepParameterDto,
    Field(discriminator="kind"),
]


class ResearchCalculationInputDto(_StrictDto):
    input_name: str
    source: str | ResearchVariableRefDto


class ResearchCalculationInstanceDto(_StrictDto):
    instance_key: str
    type_reference: ResearchCalculationTypeReferenceDto
    parameters: dict[str, ResearchParameterBindingDto]
    published_outputs: tuple[str, ...]
    input_bindings: tuple[ResearchCalculationInputDto, ...]
    primary_output: str | None


class ResearchSignalsDto(_StrictDto):
    entry: ResearchExpressionDto | None
    exit: ResearchExpressionDto | None


class ResearchStatisticsNumericDto(_StrictDto):
    representation: str
    precision: StrictInt
    output_quantum: str
    rounding: str


class ResearchStatisticsDefinitionRequestDto(_StrictDto):
    schema_version: StrictInt
    method: OnlyResearchStatisticsMethod
    minimum_observations: StrictInt
    pairing_policy: OnlyResearchPairingPolicy
    universe_policy: OnlyResearchUniversePolicy
    rank_tie_method: OnlyResearchRankTieMethod
    weighting: OnlyResearchWeighting
    numeric: ResearchStatisticsNumericDto


class ResearchStatisticsRequestDto(_StrictDto):
    variable: ResearchVariableRefDto
    target_instance_key: str
    definition: ResearchStatisticsDefinitionRequestDto


class ResearchDefinitionRequestDto(_StrictDto):
    schema_version: StrictInt
    dataset: ResearchDatasetSelectionDto
    calculations: tuple[ResearchCalculationInstanceDto, ...]
    eligibility: ResearchExpressionDto | None
    signals: ResearchSignalsDto
    targets: tuple[ResearchCalculationInstanceDto, ...]
    statistics: tuple[ResearchStatisticsRequestDto, ...]
    display_metadata: dict[str, JsonValue]

    def to_domain(self) -> OnlyResearchDefinition:
        return OnlyResearchDefinition.from_dict(self.model_dump(mode="json"))


class ResearchDefinitionCandidateDto(_StrictDto):
    ordinal: int
    candidate_fingerprint: str
    assignment: dict[str, ResearchScalarDto]
    calculation_fingerprint: str
    graph_fingerprint: str


class ResearchPublishedVariableDto(_StrictDto):
    instance_key: str
    output_name: str
    data_type: str
    semantic_type: str


class ResearchDefinitionResolutionDto(_StrictDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    authoring_definition_fingerprint: str
    resolved_definition_fingerprint: str
    dataset_snapshot_fingerprint: str
    specification_fingerprint: str
    resolved_dataset_definition: dict[str, JsonValue]
    instrument_count: int
    candidate_count: int
    candidates: tuple[ResearchDefinitionCandidateDto, ...]
    published_variables: tuple[ResearchPublishedVariableDto, ...]
    exact_specification: dict[str, JsonValue]
    diagnostics: tuple[JsonValue, ...]

    @classmethod
    def from_model(cls, value: OnlyResearchDefinitionResolution) -> ResearchDefinitionResolutionDto:
        return cls(
            authoring_definition_fingerprint=value.authoring_definition_fingerprint,
            resolved_definition_fingerprint=value.resolved_definition_fingerprint,
            dataset_snapshot_fingerprint=value.dataset_snapshot_fingerprint,
            specification_fingerprint=value.specification_fingerprint,
            resolved_dataset_definition=cast(dict[str, JsonValue], dict(value.dataset_definition.to_dict())),
            instrument_count=len(value.dataset_definition.instruments),
            candidate_count=len(value.candidates),
            candidates=tuple(
                ResearchDefinitionCandidateDto(
                    ordinal=item.ordinal,
                    candidate_fingerprint=item.candidate_fingerprint,
                    assignment={
                        name: ResearchScalarDto.from_scalar(assignment) for name, assignment in item.assignment.items()
                    },
                    calculation_fingerprint=item.calculation_fingerprint,
                    graph_fingerprint=item.graph_fingerprint,
                )
                for item in value.candidates
            ),
            published_variables=tuple(
                ResearchPublishedVariableDto(
                    instance_key=item.variable.instance_key,
                    output_name=item.variable.output_name,
                    data_type=item.data_type.value,
                    semantic_type=item.semantic_type,
                )
                for item in value.published_variables
            ),
            exact_specification=cast(dict[str, JsonValue], dict(value.specification.to_dict())),
            diagnostics=(),
        )


class ResearchDefinitionErrorDto(_StrictDto):
    phase: str
    code: str
    path: str
    detail: str


class ResearchDefinitionErrorEnvelopeDto(_StrictDto):
    error: ResearchDefinitionErrorDto


__all__ = [name for name in globals() if name.startswith("Research")]
