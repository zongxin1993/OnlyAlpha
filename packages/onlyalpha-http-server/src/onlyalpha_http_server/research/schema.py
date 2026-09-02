"""Versioned transport DTOs for the Research Query read model."""

from __future__ import annotations

from datetime import UTC
from typing import Annotated, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from onlyalpha.calculation import OnlyCalculationScalar, only_calculation_scalar_to_dict
from onlyalpha.canonical import only_canonical_payload
from onlyalpha.research.query import (
    OnlyResearchArtifactSummary,
    OnlyResearchCandidateCatalog,
    OnlyResearchCandidateGraph,
    OnlyResearchMarketPoint,
    OnlyResearchPublishedSeriesCatalog,
    OnlyResearchScientificSeriesPage,
    OnlyResearchSignalPoint,
    OnlyResearchStatisticPoint,
    OnlyResearchStatisticsCatalog,
    OnlyResearchStatisticsDefinitionDescriptor,
    OnlyResearchStatisticsDescriptor,
    OnlyResearchStatisticSeriesPage,
    OnlyResearchVariablePoint,
)

RESEARCH_API_SCHEMA_VERSION: Literal[2] = 2
Sha256Dto = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
DecimalTextDto = Annotated[str, StringConstraints(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")]
IntegerTextDto = Annotated[str, StringConstraints(pattern=r"^-?(?:0|[1-9][0-9]*)$")]


class _ReadDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ResearchErrorDto(_ReadDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    code: str
    detail: str


class ResearchArtifactSummaryDto(_ReadDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    research_result_plan_fingerprint: str
    research_result_content_fingerprint: str
    research_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    artifact_content_fingerprint: str
    research_result_schema_version: int
    artifact_profile: str
    artifact_schema_version: int
    statistics_count: int
    row_count: int
    candidate_count: int
    published_series_count: int
    signal_series_count: int
    market_row_count: int
    instrument_ids: tuple[str, ...]
    created_at: str

    @classmethod
    def from_model(cls, value: OnlyResearchArtifactSummary) -> ResearchArtifactSummaryDto:
        created_at = value.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return cls(
            research_result_plan_fingerprint=value.research_result_plan_fingerprint,
            research_result_content_fingerprint=value.research_result_content_fingerprint,
            research_result_fingerprint=value.research_result_fingerprint,
            dataset_snapshot_fingerprint=value.dataset_snapshot_fingerprint,
            artifact_content_fingerprint=value.artifact_content_fingerprint,
            research_result_schema_version=value.research_result_schema_version,
            artifact_profile=value.artifact_profile,
            artifact_schema_version=value.artifact_schema_version,
            statistics_count=value.statistics_count,
            row_count=value.row_count,
            candidate_count=value.candidate_count,
            published_series_count=value.published_series_count,
            signal_series_count=value.signal_series_count,
            market_row_count=value.market_row_count,
            instrument_ids=value.instrument_ids,
            created_at=created_at,
        )


class ResearchSeriesReferenceDto(_ReadDto):
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str


class ResearchNumericDefinitionDto(_ReadDto):
    representation: str
    precision: int
    output_quantum: str
    rounding: str


class ResearchStatisticsDefinitionDto(_ReadDto):
    method: str
    minimum_observations: int
    pairing_policy: str
    universe_policy: str
    rank_tie_method: str
    weighting: str
    numeric: ResearchNumericDefinitionDto

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticsDefinitionDescriptor) -> ResearchStatisticsDefinitionDto:
        return cls(
            method=value.method,
            minimum_observations=value.minimum_observations,
            pairing_policy=value.pairing_policy,
            universe_policy=value.universe_policy,
            rank_tie_method=value.rank_tie_method,
            weighting=value.weighting,
            numeric=ResearchNumericDefinitionDto(
                representation=value.numeric.representation,
                precision=value.numeric.precision,
                output_quantum=format(value.numeric.output_quantum, "f"),
                rounding=value.numeric.rounding,
            ),
        )


class ResearchStatisticsDescriptorDto(_ReadDto):
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    statistics_result_schema_version: int
    row_count: int
    feature: ResearchSeriesReferenceDto
    target: ResearchSeriesReferenceDto
    definition: ResearchStatisticsDefinitionDto

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticsDescriptor) -> ResearchStatisticsDescriptorDto:
        return cls(
            statistics_fingerprint=value.statistics_fingerprint,
            statistics_result_fingerprint=value.statistics_result_fingerprint,
            result_content_fingerprint=value.result_content_fingerprint,
            statistics_result_schema_version=value.statistics_result_schema_version,
            row_count=value.row_count,
            feature=ResearchSeriesReferenceDto(
                calculation_fingerprint=value.feature.calculation_fingerprint,
                node_fingerprint=value.feature.node_fingerprint,
                output_name=value.feature.output_name,
            ),
            target=ResearchSeriesReferenceDto(
                calculation_fingerprint=value.target.calculation_fingerprint,
                node_fingerprint=value.target.node_fingerprint,
                output_name=value.target.output_name,
            ),
            definition=ResearchStatisticsDefinitionDto.from_model(value.definition),
        )


class ResearchStatisticsCatalogDto(_ReadDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    research_result_fingerprint: str
    statistics: tuple[ResearchStatisticsDescriptorDto, ...]

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticsCatalog) -> ResearchStatisticsCatalogDto:
        return cls(
            research_result_fingerprint=value.research_result_fingerprint,
            statistics=tuple(ResearchStatisticsDescriptorDto.from_model(item) for item in value.statistics),
        )


class ResearchStatisticPointDto(_ReadDto):
    ts_event_ns: str
    statistic_value: str | None
    sample_count: int
    status: str

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticPoint) -> ResearchStatisticPointDto:
        return cls(
            ts_event_ns=str(value.ts_event_ns),
            statistic_value=None if value.statistic_value is None else format(value.statistic_value, "f"),
            sample_count=value.sample_count,
            status=value.status,
        )


class ResearchStatisticSeriesPageDto(_ReadDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    research_result_fingerprint: str
    statistics_fingerprint: str
    points: tuple[ResearchStatisticPointDto, ...]
    has_more: bool
    next_after_ts_event_ns: str | None

    @classmethod
    def from_model(cls, value: OnlyResearchStatisticSeriesPage) -> ResearchStatisticSeriesPageDto:
        return cls(
            research_result_fingerprint=value.research_result_fingerprint,
            statistics_fingerprint=value.statistics_fingerprint,
            points=tuple(ResearchStatisticPointDto.from_model(item) for item in value.points),
            has_more=value.has_more,
            next_after_ts_event_ns=(
                None if value.next_after_ts_event_ns is None else str(value.next_after_ts_event_ns)
            ),
        )


class ResearchCandidateDto(_ReadDto):
    candidate_fingerprint: Sha256Dto
    candidate_calculation_id: str
    assignment: dict[str, StrictBool | StrictInt | StrictStr | None]
    assignment_types: dict[str, Literal["NULL", "BOOLEAN", "INTEGER", "DECIMAL", "STRING"]]
    calculation_fingerprint: Sha256Dto
    graph_fingerprint: Sha256Dto
    statistics_fingerprints: tuple[Sha256Dto, ...]
    signal_roles: tuple[Literal["ELIGIBILITY", "ENTRY_SIGNAL", "EXIT_SIGNAL"], ...]


class ResearchCandidateCatalogDto(_ReadDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    research_result_fingerprint: str
    candidates: tuple[ResearchCandidateDto, ...]

    @classmethod
    def from_model(cls, value: OnlyResearchCandidateCatalog) -> ResearchCandidateCatalogDto:
        return cls(
            research_result_fingerprint=value.research_result_fingerprint,
            candidates=tuple(
                ResearchCandidateDto(
                    candidate_fingerprint=item.candidate_fingerprint,
                    candidate_calculation_id=item.candidate_calculation_id,
                    assignment=only_canonical_payload(dict(item.assignment)),  # type: ignore[arg-type]
                    assignment_types=dict(item.assignment_types),
                    calculation_fingerprint=item.calculation_fingerprint,
                    graph_fingerprint=item.graph_fingerprint,
                    statistics_fingerprints=item.statistics_fingerprints,
                    signal_roles=item.signal_roles,
                )
                for item in value.candidates
            ),
        )


class ResearchPublishedSeriesDto(_ReadDto):
    candidate_fingerprint: str | None
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str
    value_kind: str


class ResearchPublishedSeriesCatalogDto(_ReadDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    research_result_fingerprint: str
    series: tuple[ResearchPublishedSeriesDto, ...]

    @classmethod
    def from_model(cls, value: OnlyResearchPublishedSeriesCatalog) -> ResearchPublishedSeriesCatalogDto:
        return cls(
            research_result_fingerprint=value.research_result_fingerprint,
            series=tuple(
                ResearchPublishedSeriesDto(
                    candidate_fingerprint=item.candidate_fingerprint,
                    calculation_fingerprint=item.calculation_fingerprint,
                    node_fingerprint=item.node_fingerprint,
                    output_name=item.output_name,
                    value_kind=item.value_kind,
                )
                for item in value.series
            ),
        )


class ResearchMarketPointDto(_ReadDto):
    instrument_id: str
    ts_event_ns: str
    open: str
    high: str
    low: str
    close: str
    volume: str


class ResearchVariablePointDto(_ReadDto):
    instrument_id: str
    ts_event_ns: str
    value_kind: str
    decimal_value: str | None
    integer_value: str | None
    boolean_value: bool | None
    string_value: str | None


class ResearchSignalPointDto(_ReadDto):
    instrument_id: str
    ts_event_ns: str
    value: bool | None


class ResearchScientificSeriesPageDto(_ReadDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    research_result_fingerprint: str
    points: tuple[ResearchMarketPointDto | ResearchVariablePointDto | ResearchSignalPointDto, ...]
    has_more: bool
    next_after_ts_event_ns: str | None

    @classmethod
    def from_model(cls, value: OnlyResearchScientificSeriesPage) -> ResearchScientificSeriesPageDto:
        points: list[ResearchMarketPointDto | ResearchVariablePointDto | ResearchSignalPointDto] = []
        for item in value.points:
            if isinstance(item, OnlyResearchMarketPoint):
                points.append(
                    ResearchMarketPointDto(
                        instrument_id=item.instrument_id,
                        ts_event_ns=str(item.ts_event_ns),
                        open=format(item.open, "f"),
                        high=format(item.high, "f"),
                        low=format(item.low, "f"),
                        close=format(item.close, "f"),
                        volume=format(item.volume, "f"),
                    )
                )
            elif isinstance(item, OnlyResearchVariablePoint):
                points.append(
                    ResearchVariablePointDto(
                        instrument_id=item.instrument_id,
                        ts_event_ns=str(item.ts_event_ns),
                        value_kind=item.value_kind,
                        decimal_value=item.decimal_value,
                        integer_value=item.integer_value,
                        boolean_value=item.boolean_value,
                        string_value=item.string_value,
                    )
                )
            elif isinstance(item, OnlyResearchSignalPoint):
                points.append(
                    ResearchSignalPointDto(
                        instrument_id=item.instrument_id, ts_event_ns=str(item.ts_event_ns), value=item.value
                    )
                )
        return cls(
            research_result_fingerprint=value.research_result_fingerprint,
            points=tuple(points),
            has_more=value.has_more,
            next_after_ts_event_ns=None if value.next_after_ts_event_ns is None else str(value.next_after_ts_event_ns),
        )


class ResearchGraphNullScalarDto(_ReadDto):
    type: Literal["NULL"]
    value: None


class ResearchGraphBooleanScalarDto(_ReadDto):
    type: Literal["BOOLEAN"]
    value: StrictBool


class ResearchGraphIntegerScalarDto(_ReadDto):
    type: Literal["INTEGER"]
    value: IntegerTextDto


class ResearchGraphDecimalScalarDto(_ReadDto):
    type: Literal["DECIMAL"]
    value: DecimalTextDto


class ResearchGraphStringScalarDto(_ReadDto):
    type: Literal["STRING"]
    value: StrictStr


ResearchGraphScalarDto = Annotated[
    ResearchGraphNullScalarDto
    | ResearchGraphBooleanScalarDto
    | ResearchGraphIntegerScalarDto
    | ResearchGraphDecimalScalarDto
    | ResearchGraphStringScalarDto,
    Field(discriminator="type"),
]


class ResearchGraphPortDto(_ReadDto):
    name: str
    data_type: Literal["DECIMAL", "INTEGER", "BOOLEAN", "STRING"]
    nullable: bool
    dimensions: tuple[str, ...]
    semantic_type: str
    unit: str | None


class ResearchGraphReferenceDto(_ReadDto):
    node_fingerprint: Sha256Dto | None
    output_name: str
    source: str | None

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if (self.node_fingerprint is None) == (self.source is None):
            raise ValueError("Graph input must select exactly one node or external source")
        return self


class ResearchGraphWarmupDto(_ReadDto):
    minimum_observations: int
    ready_condition: str
    pre_ready_output: Literal["NULL", "PARTIAL"]
    initialization: str


class ResearchGraphNumericDto(_ReadDto):
    representation: str
    precision: int
    output_quantum: DecimalTextDto | None
    rounding: str


class ResearchGraphDefinitionDto(_ReadDto):
    schema_version: Literal[2]
    kind: Literal["INDICATOR", "FACTOR", "TARGET", "PREDICATE"]
    type_id: str
    semantic_version: str
    parameters: dict[str, ResearchGraphScalarDto]
    inputs: tuple[ResearchGraphPortDto, ...]
    input_bindings: dict[str, ResearchGraphReferenceDto]
    outputs: tuple[ResearchGraphPortDto, ...]
    warmup: ResearchGraphWarmupDto
    missing_values: Literal["FAIL", "SKIP", "PROPAGATE", "RESET"]
    timestamp: Literal["BAR_OPEN", "BAR_CLOSE", "EVENT_TIME", "OBSERVATION_TIME", "AVAILABILITY_TIME"]
    numeric: ResearchGraphNumericDto
    factor_kind: Literal["TIME_SERIES", "CROSS_SECTION"] | None
    extensions: dict[str, ResearchGraphScalarDto]

    @model_validator(mode="after")
    def validate_ports(self) -> Self:
        input_names = tuple(item.name for item in self.inputs)
        output_names = tuple(item.name for item in self.outputs)
        if len(set(input_names)) != len(input_names) or len(set(output_names)) != len(output_names):
            raise ValueError("Graph ports must be unique")
        if set(input_names) != set(self.input_bindings):
            raise ValueError("Graph input bindings must exactly match input ports")
        if (self.kind == "FACTOR") != (self.factor_kind is not None):
            raise ValueError("Graph factor_kind does not match calculation kind")
        return self


class ResearchGraphNodeDto(_ReadDto):
    node_fingerprint: Sha256Dto
    definition: ResearchGraphDefinitionDto
    alias: str | None


class ResearchCalculationGraphDto(_ReadDto):
    schema_version: Literal[1]
    nodes: tuple[ResearchGraphNodeDto, ...]

    @model_validator(mode="after")
    def validate_topology(self) -> Self:
        identities = {node.node_fingerprint for node in self.nodes}
        if len(identities) != len(self.nodes):
            raise ValueError("Graph nodes must be unique")
        if any(
            reference.node_fingerprint is not None and reference.node_fingerprint not in identities
            for node in self.nodes
            for reference in node.definition.input_bindings.values()
        ):
            raise ValueError("Graph dependency is missing")
        return self


class ResearchCandidateGraphDto(_ReadDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    research_result_fingerprint: Sha256Dto
    candidate_fingerprint: Sha256Dto
    calculation_fingerprint: Sha256Dto
    graph_fingerprint: Sha256Dto
    graph: ResearchCalculationGraphDto

    @classmethod
    def from_model(cls, value: OnlyResearchCandidateGraph) -> ResearchCandidateGraphDto:
        return cls(
            research_result_fingerprint=value.research_result_fingerprint,
            candidate_fingerprint=value.candidate_fingerprint,
            calculation_fingerprint=value.calculation_fingerprint,
            graph_fingerprint=value.graph_fingerprint,
            graph=ResearchCalculationGraphDto(
                schema_version=cast(Literal[1], value.graph.schema_version),
                nodes=tuple(
                    ResearchGraphNodeDto(
                        node_fingerprint=node.fingerprint,
                        definition=ResearchGraphDefinitionDto.model_validate(
                            {
                                **node.definition.to_dict(),
                                "parameters": {
                                    name: _graph_scalar_transport(scalar)
                                    for name, scalar in node.definition.parameters.items()
                                },
                                "extensions": {
                                    name: _graph_scalar_transport(scalar)
                                    for name, scalar in node.definition.extensions.items()
                                },
                            }
                        ),
                        alias=node.alias,
                    )
                    for node in value.graph.ordered_nodes
                ),
            ),
        )


def _graph_scalar_transport(value: OnlyCalculationScalar) -> dict[str, object]:
    payload = dict(only_calculation_scalar_to_dict(value))
    if payload["type"] == "INTEGER":
        payload["value"] = str(payload["value"])
    return payload
