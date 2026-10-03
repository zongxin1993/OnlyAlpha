"""Strict immutable Calculation Result V2 manifests and verified projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition

from .execution import OnlyResearchCalculationNodeOutput, OnlyResearchCalculationNodeReadiness
from .identity import only_research_calculation_fingerprint
from .result import (
    OnlyResearchCalculationResultPartitionManifest,
    _exact,
    _int,
    _mapping,
    _partition,
    _sha,
    _utc_datetime,
)
from .result_v2_identity import (
    RESEARCH_CALCULATION_RESULT_V2_SCHEMA_VERSION,
    _Descriptor,
    only_research_calculation_result_content_fingerprint_v2,
    only_research_calculation_result_fingerprint_v2,
    only_research_calculation_value_projection_fingerprint,
)


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationResultManifestV2:
    calculation_fingerprint: str
    dataset_snapshot_fingerprint: str
    calculation_graph_fingerprint: str
    calculation_graph: OnlyCalculationGraphDefinition
    value_projection_fingerprint: str
    result_content_fingerprint: str
    calculation_result_fingerprint: str
    value_partitions: tuple[OnlyResearchCalculationResultPartitionManifest, ...]
    readiness_partitions: tuple[OnlyResearchCalculationResultPartitionManifest, ...]
    created_at: datetime
    schema_version: int = RESEARCH_CALCULATION_RESULT_V2_SCHEMA_VERSION
    readiness_contract_version: int = 1

    def __post_init__(self) -> None:
        context = "Calculation Result V2"
        if not isinstance(self.calculation_graph, OnlyCalculationGraphDefinition):
            raise ValueError("canonical Graph required")
        if not isinstance(self.created_at, datetime):
            raise ValueError("typed audit datetime required")
        if type(self.value_partitions) is not tuple or type(self.readiness_partitions) is not tuple:
            raise ValueError("partition tuple required")
        if any(
            type(item) is not OnlyResearchCalculationResultPartitionManifest
            for item in (*self.value_partitions, *self.readiness_partitions)
        ):
            raise ValueError("typed partition descriptor required")
        payload = self.to_dict()
        if _int(payload, "schema_version", context) != 2 or _int(payload, "readiness_contract_version", context) != 1:
            raise ValueError("unsupported Result/readiness version")
        for name in (
            "calculation_fingerprint",
            "dataset_snapshot_fingerprint",
            "calculation_graph_fingerprint",
            "value_projection_fingerprint",
            "result_content_fingerprint",
            "calculation_result_fingerprint",
        ):
            _sha(payload, name, context)
        _utc_datetime(payload, "created_at", context)
        if (
            self.calculation_graph.fingerprint != self.calculation_graph_fingerprint
            or self.calculation_fingerprint
            != only_research_calculation_fingerprint(
                self.dataset_snapshot_fingerprint, self.calculation_graph_fingerprint
            )
        ):
            raise ValueError("Dataset/Graph/Calculation linkage mismatch")
        for name, family in (("value_partitions", "values"), ("readiness_partitions", "readiness")):
            _partitions(payload[name], family)
        if tuple((item.node_fingerprint, item.instrument_id) for item in self.value_partitions) != tuple(
            (item.node_fingerprint, item.instrument_id) for item in self.readiness_partitions
        ):
            raise ValueError("value/readiness partition bijection mismatch")
        values, readiness = _logical(self.value_partitions), _logical(self.readiness_partitions)
        if self.value_projection_fingerprint != only_research_calculation_value_projection_fingerprint(values):
            raise ValueError("value projection fingerprint mismatch")
        if self.result_content_fingerprint != only_research_calculation_result_content_fingerprint_v2(
            values, readiness
        ):
            raise ValueError("Result content fingerprint mismatch")
        if self.calculation_result_fingerprint != only_research_calculation_result_fingerprint_v2(
            self.calculation_fingerprint, self.result_content_fingerprint
        ):
            raise ValueError("Result fingerprint mismatch")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "readiness_contract_version": self.readiness_contract_version,
            "calculation_fingerprint": self.calculation_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "calculation_graph_fingerprint": self.calculation_graph_fingerprint,
            "calculation_graph": self.calculation_graph.to_dict(),
            "value_projection_fingerprint": self.value_projection_fingerprint,
            "result_content_fingerprint": self.result_content_fingerprint,
            "calculation_result_fingerprint": self.calculation_result_fingerprint,
            "value_partitions": [item.to_dict() for item in self.value_partitions],
            "readiness_partitions": [item.to_dict() for item in self.readiness_partitions],
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationResultManifestV2:
        context = "Calculation Result V2"
        _exact(
            payload,
            {
                "schema_version",
                "readiness_contract_version",
                "calculation_fingerprint",
                "dataset_snapshot_fingerprint",
                "calculation_graph_fingerprint",
                "calculation_graph",
                "value_projection_fingerprint",
                "result_content_fingerprint",
                "calculation_result_fingerprint",
                "value_partitions",
                "readiness_partitions",
                "created_at",
            },
            context,
        )
        if _int(payload, "schema_version", context) != 2 or _int(payload, "readiness_contract_version", context) != 1:
            raise ValueError("unsupported Result/readiness version")
        graph = OnlyCalculationGraphDefinition.from_dict(_mapping(payload["calculation_graph"], "Graph"))
        graph_fingerprint = _sha(payload, "calculation_graph_fingerprint", context)
        dataset = _sha(payload, "dataset_snapshot_fingerprint", context)
        calculation = _sha(payload, "calculation_fingerprint", context)
        values = _partitions(payload["value_partitions"], "values")
        readiness = _partitions(payload["readiness_partitions"], "readiness")
        projection = _sha(payload, "value_projection_fingerprint", context)
        content = _sha(payload, "result_content_fingerprint", context)
        result = _sha(payload, "calculation_result_fingerprint", context)
        return cls(
            calculation,
            dataset,
            graph_fingerprint,
            graph,
            projection,
            content,
            result,
            values,
            readiness,
            _utc_datetime(payload, "created_at", context),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationResultV2:
    manifest: OnlyResearchCalculationResultManifestV2
    outputs: tuple[OnlyResearchCalculationNodeOutput, ...]
    readiness: tuple[OnlyResearchCalculationNodeReadiness, ...]


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationResultVerificationV2:
    valid: bool
    calculation_fingerprint: str
    calculation_result_fingerprint: str
    partition_count: int
    total_row_count: int
    readiness_row_count: int


def _partitions(raw: object, family: str) -> tuple[OnlyResearchCalculationResultPartitionManifest, ...]:
    if not isinstance(raw, list):
        raise ValueError("partitions must be an array")
    partitions = tuple(_partition(item) for item in raw)
    keys = tuple((item.node_fingerprint, item.instrument_id) for item in partitions)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("partition order/uniqueness mismatch")
    for index, item in enumerate(partitions):
        if item.relative_path != f"{family}/p-{index:06d}.parquet":
            raise ValueError("partition path/family mismatch")
        if not item.instrument_id or item.instrument_id.strip() != item.instrument_id:
            raise ValueError("invalid instrument identity")
    return partitions


def _logical(partitions: tuple[OnlyResearchCalculationResultPartitionManifest, ...]) -> tuple[_Descriptor, ...]:
    return tuple(
        (item.node_fingerprint, item.instrument_id, item.row_count, item.semantic_fingerprint, item.arrow_schema)
        for item in partitions
    )
