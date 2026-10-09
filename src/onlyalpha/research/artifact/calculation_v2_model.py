"""Strict portable copied-fact contract for the content-addressed Calculation V2 profile."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.quant_assets.retained_generation import OnlyRetainedRuntimeGenerationProofV1
from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceV2
from onlyalpha.research.calculation.execution_provenance import OnlyResearchRuntimeExecutionProvenanceV1
from onlyalpha.research.calculation.result_v2 import OnlyResearchCalculationResultManifestV2
from onlyalpha.research.dataset.manifest import OnlyResearchDatasetSnapshot
from onlyalpha.research.dataset.strict import (
    require_exact_fields,
    require_int,
    require_list,
    require_mapping,
    require_sha256,
    require_str,
    require_utc_datetime,
)
from onlyalpha.research.result.result import OnlyResearchResultManifest

RESEARCH_CALCULATION_ARTIFACT_V2_PROFILE = "RESEARCH_CALCULATION_V2"
RESEARCH_CALCULATION_ARTIFACT_V2_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationArtifactFileV2:
    relative_path: str
    byte_sha256: str
    byte_size: int

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationArtifactFileV2:
        require_exact_fields(payload, set(cls.__dataclass_fields__), "Artifact file")
        size = require_int(payload, "byte_size", "Artifact file")
        if size < 1:
            raise ValueError("Artifact file size must be positive")
        return cls(
            require_str(payload, "relative_path", "Artifact file"),
            require_sha256(payload, "byte_sha256", "Artifact file"),
            size,
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationArtifactManifestV2:
    result: OnlyResearchResultManifest
    dataset: OnlyResearchDatasetSnapshot
    calculations: tuple[OnlyResearchCalculationResultManifestV2, ...]
    selected_evidence: tuple[OnlyResearchCalculationExecutionEvidenceV2, ...]
    retained_generation: OnlyRetainedRuntimeGenerationProofV1
    files: tuple[OnlyResearchCalculationArtifactFileV2, ...]
    created_at: datetime
    profile: str = RESEARCH_CALCULATION_ARTIFACT_V2_PROFILE
    schema_version: int = RESEARCH_CALCULATION_ARTIFACT_V2_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            self.profile != RESEARCH_CALCULATION_ARTIFACT_V2_PROFILE
            or type(self.schema_version) is not int
            or self.schema_version != 2
        ):
            raise ValueError("unsupported Calculation Artifact profile/schema")
        if type(self.result) is not OnlyResearchResultManifest or self.result.schema_version != 4:
            raise ValueError("Calculation Artifact V2 requires Result V4")
        for value, parser in (
            (self.result, OnlyResearchResultManifest.from_dict),
            (self.dataset, OnlyResearchDatasetSnapshot.from_dict),
        ):
            if parser(value.to_dict()) != value:
                raise ValueError("retained owning manifest differs")
        for values, expected_type in (
            (self.calculations, OnlyResearchCalculationResultManifestV2),
            (self.selected_evidence, OnlyResearchCalculationExecutionEvidenceV2),
            (self.files, OnlyResearchCalculationArtifactFileV2),
        ):
            if type(values) is not tuple or any(type(value) is not expected_type for value in values):
                raise ValueError("Artifact inventory requires exact owning contracts")
        if (
            type(self.retained_generation) is not OnlyRetainedRuntimeGenerationProofV1
            or OnlyRetainedRuntimeGenerationProofV1.from_dict(self.retained_generation.to_dict())
            != self.retained_generation
        ):
            raise ValueError("retained generation proof differs")
        if self.dataset.snapshot_fingerprint != self.result.dataset_snapshot_fingerprint:
            raise ValueError("Artifact Dataset/Result relation differs")
        expected = tuple(member.calculation_fingerprint for member in self.result.calculation_results)
        if (
            tuple(item.calculation_fingerprint for item in self.calculations) != expected
            or tuple(item.calculation_fingerprint for item in self.selected_evidence) != expected
        ):
            raise ValueError("Artifact Calculation/Evidence selection must be a complete canonical bijection")
        self._require_relations()
        if tuple(item.relative_path for item in self.files) != tuple(sorted(self.partition_descriptors)):
            raise ValueError("Artifact file set must be derived from complete canonical manifests")
        for item in self.files:
            if OnlyResearchCalculationArtifactFileV2.from_dict(item.to_dict()) != item:
                raise ValueError("Artifact file descriptor differs")
            if item.byte_sha256 != self.partition_descriptors[item.relative_path][0]:
                raise ValueError("Artifact physical hash differs from owning partition manifest")
        require_utc_datetime({"created_at": self.created_at.isoformat()}, "created_at", "Artifact")

    @property
    def expected_runtime_provenance(self) -> OnlyResearchRuntimeExecutionProvenanceV1:
        proof = self.retained_generation
        return OnlyResearchRuntimeExecutionProvenanceV1(
            proof.generation.runtime_generation_fingerprint,
            proof.validation.validation_evidence_fingerprint,
            proof.generation.core_execution.fingerprint,
            proof.generation.catalog_generation_fingerprint,
        )

    def _require_relations(self) -> None:
        manifests = {item.calculation_fingerprint: item for item in self.calculations}
        members = {item.calculation_fingerprint: item for item in self.result.plan.calculations}
        used_implementations: set[str] = set()
        for reference, evidence in zip(self.result.calculation_results, self.selected_evidence, strict=True):
            manifest = manifests[reference.calculation_fingerprint]
            if (
                OnlyResearchCalculationResultManifestV2.from_dict(manifest.to_dict()) != manifest
                or OnlyResearchCalculationExecutionEvidenceV2.from_dict(evidence.to_dict()) != evidence
            ):
                raise ValueError("retained Calculation/Evidence contract differs")
            if (
                manifest.calculation_result_fingerprint,
                manifest.dataset_snapshot_fingerprint,
                manifest.calculation_graph_fingerprint,
            ) != (
                reference.calculation_result_fingerprint,
                self.dataset.snapshot_fingerprint,
                members[reference.calculation_fingerprint].graph_fingerprint,
            ):
                raise ValueError("Artifact Result/Calculation/Dataset/Graph relation differs")
            if (
                evidence.calculation_result_fingerprint,
                evidence.result_content_fingerprint,
                evidence.dataset_snapshot_fingerprint,
                evidence.calculation_graph_fingerprint,
            ) != (
                manifest.calculation_result_fingerprint,
                manifest.result_content_fingerprint,
                manifest.dataset_snapshot_fingerprint,
                manifest.calculation_graph_fingerprint,
            ):
                raise ValueError("Artifact Evidence/Calculation relation differs")
            if (
                evidence.runtime_execution_provenance != self.expected_runtime_provenance
                or evidence.authoring_generation_fingerprint is not None
            ):
                raise ValueError("Artifact requires complete exact Runtime provenance; authoring proof is unsupported")
            bindings = tuple(
                (item.node_fingerprint, item.research_implementation_fingerprint)
                for item in evidence.research_implementation_bindings
            )
            self.retained_generation.require_graph_implementations(manifest.calculation_graph, bindings)
            used_implementations.update(item[1] for item in bindings)
        if used_implementations != {
            item.implementation_fingerprint for item in self.retained_generation.implementation_manifests
        }:
            raise ValueError("Artifact selected implementation manifest coverage differs")
        for series in self.result.plan.published_series:
            graph = manifests[series.calculation_fingerprint].calculation_graph
            node = next((item for item in graph.nodes if item.fingerprint == series.node_fingerprint), None)
            if node is None or series.output_name not in {item.name for item in node.definition.outputs}:
                raise ValueError("Artifact published series membership differs")

    @property
    def partition_descriptors(self) -> dict[str, tuple[str, int, object, str]]:
        """Fixed paths with owning byte hash, count, Arrow schema and logical identity."""
        result: dict[str, tuple[str, int, object, str]] = {}
        for index, item in enumerate(self.dataset.partitions):
            if item.partition_id != f"p-{index:06d}" or item.relative_path != f"data/p-{index:06d}.parquet":
                raise ValueError("Artifact Dataset partitions must be canonical")
            result[f"dataset/{item.relative_path}"] = (
                item.byte_sha256,
                item.row_count,
                self.dataset.dataset_schema.semantic_payload(),
                item.semantic_fingerprint,
            )
        for manifest in self.calculations:
            for calculation_partition in (*manifest.value_partitions, *manifest.readiness_partitions):
                result[f"calculations/{manifest.calculation_fingerprint}/{calculation_partition.relative_path}"] = (
                    calculation_partition.byte_sha256,
                    calculation_partition.row_count,
                    calculation_partition.arrow_schema,
                    calculation_partition.semantic_fingerprint,
                )
        return result

    @property
    def artifact_content_fingerprint(self) -> str:
        result = self.result.to_dict()
        result.pop("created_at")
        dataset = _logical_manifest(self.dataset.to_dict(), ("partitions",))
        calculations = [
            _logical_manifest(item.to_dict(), ("value_partitions", "readiness_partitions"))
            for item in self.calculations
        ]
        return only_canonical_fingerprint(
            {
                "profile": self.profile,
                "schema_version": self.schema_version,
                "result": result,
                "dataset": dataset,
                "calculations": calculations,
                "selected_evidence": [item.to_dict() for item in self.selected_evidence],
                "retained_generation": self.retained_generation.to_dict(),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "schema_version": self.schema_version,
            "result": self.result.to_dict(),
            "dataset": self.dataset.to_dict(),
            "calculations": [item.to_dict() for item in self.calculations],
            "selected_evidence": [item.to_dict() for item in self.selected_evidence],
            "retained_generation": self.retained_generation.to_dict(),
            "files": [item.to_dict() for item in self.files],
            "created_at": self.created_at.isoformat(),
            "artifact_content_fingerprint": self.artifact_content_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationArtifactManifestV2:
        require_exact_fields(
            payload, set(cls.__dataclass_fields__) | {"artifact_content_fingerprint"}, "Artifact manifest"
        )
        result = cls(
            OnlyResearchResultManifest.from_dict(require_mapping(payload["result"], "Artifact Result")),
            OnlyResearchDatasetSnapshot.from_dict(require_mapping(payload["dataset"], "Artifact Dataset")),
            tuple(
                OnlyResearchCalculationResultManifestV2.from_dict(require_mapping(item, "Artifact Calculation"))
                for item in require_list(payload["calculations"], "Artifact Calculations")
            ),
            tuple(
                OnlyResearchCalculationExecutionEvidenceV2.from_dict(require_mapping(item, "Artifact Evidence"))
                for item in require_list(payload["selected_evidence"], "Artifact Evidence")
            ),
            OnlyRetainedRuntimeGenerationProofV1.from_dict(
                require_mapping(payload["retained_generation"], "Artifact generation")
            ),
            tuple(
                OnlyResearchCalculationArtifactFileV2.from_dict(require_mapping(item, "Artifact file"))
                for item in require_list(payload["files"], "Artifact files")
            ),
            require_utc_datetime(payload, "created_at", "Artifact"),
            require_str(payload, "profile", "Artifact"),
            require_int(payload, "schema_version", "Artifact"),
        )
        if require_sha256(payload, "artifact_content_fingerprint", "Artifact") != result.artifact_content_fingerprint:
            raise ValueError("Artifact logical identity differs")
        if only_canonical_json(result.to_dict()) != only_canonical_json(payload):
            raise ValueError("Artifact nested representation is noncanonical")
        return result


def _logical_manifest(payload: dict[str, object], partitions: tuple[str, ...]) -> dict[str, object]:
    payload.pop("created_at")
    for name in partitions:
        for item in cast(list[dict[str, object]], payload[name]):
            item.pop("relative_path")
            item.pop("byte_sha256")
    return payload
