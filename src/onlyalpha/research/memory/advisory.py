"""Versioned, disposable near-duplicate advice over verified Research facts."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, cast

from onlyalpha.calculation.definition import OnlyCalculationDefinition, OnlyCalculationScalar
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.evaluation.subject import OnlyExactEvaluationIntentSubjectV1
from onlyalpha.research.memory.projector import (
    OnlyExperimentMemoryProjectionV1,
    OnlyMemoryCutReader,
    OnlyMemoryProjectionRecordV1,
    OnlyMemorySourceRefV1,
    only_load_cut_observations,
)
from onlyalpha.research.memory.query import (
    OnlyExactEvaluationHistorySelectorV1,
    OnlyExactSemanticHistorySelectorV1,
    OnlyExactStatisticsReferenceV1,
)
from onlyalpha.research.memory.source_manifest import MANDATORY_FAMILIES, OnlyMemoryProjectionError
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.source_cut import OnlySourceObservationV1
from onlyalpha.research.specification.model import OnlyResearchSpecification

REPRESENTATION_SCHEMA_VERSION = 1
QUERY_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1
STRUCTURED_ALGORITHM_ID = "STRUCTURED_NEAR_DUPLICATE"
STRUCTURED_ALGORITHM_VERSION = "1"
_COMPARISON_DIMENSIONS = frozenset({"DATASET", "EVALUATION_CONTEXT", "OPERATORS", "OUTPUT", "PARAMETERS", "TOPOLOGY"})


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is required")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("score must be finite")
    text = format(value.normalize(), "f")
    return "0" if text == "-0" else text


def _decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a canonical decimal string")
    try:
        result = Decimal(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a canonical decimal string") from exc
    if _decimal_text(result) != value:
        raise ValueError(f"{name} must be a canonical decimal string")
    return result


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchAdvisorySourceRefV1:
    source_kind: str
    native_locator: str
    source_identity: str
    source_revision: str

    def __post_init__(self) -> None:
        _text(self.source_kind, "source_kind")
        _text(self.native_locator, "native_locator")
        _text(self.source_identity, "source_identity")
        _sha(self.source_revision, "source_revision")

    def to_dict(self) -> dict[str, str]:
        return {
            "source_kind": self.source_kind,
            "native_locator": self.native_locator,
            "source_identity": self.source_identity,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchAdvisorySourceRefV1:
        if set(payload) != {"source_kind", "native_locator", "source_identity", "source_revision"}:
            raise ValueError("advisory source fields are invalid")
        return cls(
            *(
                cast(str, payload[name])
                for name in ("source_kind", "native_locator", "source_identity", "source_revision")
            )
        )


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchAdvisoryParameterV1:
    key: str
    value_kind: str
    canonical_value: str

    def __post_init__(self) -> None:
        _text(self.key, "parameter key")
        if self.value_kind not in {"BOOLEAN", "DECIMAL", "INTEGER", "NONE", "STRING"}:
            raise ValueError("parameter value kind is unsupported")
        _text(self.canonical_value, "canonical parameter value")

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "value_kind": self.value_kind, "canonical_value": self.canonical_value}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchAdvisoryParameterV1:
        if set(payload) != {"key", "value_kind", "canonical_value"}:
            raise ValueError("advisory parameter fields are invalid")
        return cls(cast(str, payload["key"]), cast(str, payload["value_kind"]), cast(str, payload["canonical_value"]))


@dataclass(frozen=True, slots=True)
class OnlyResearchAdvisoryRepresentationV1:
    source_ref: OnlyResearchAdvisorySourceRefV1
    projection_revision: str
    source_cut_fingerprint: str
    operator_features: tuple[str, ...]
    topology_features: tuple[str, ...]
    parameter_features: tuple[OnlyResearchAdvisoryParameterV1, ...]
    output_features: tuple[str, ...]
    dataset_snapshot_fingerprint: str
    evaluation_context_fingerprint: str
    representation_schema_version: int = REPRESENTATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.source_ref, OnlyResearchAdvisorySourceRefV1):
            raise ValueError("advisory source reference is required")
        _sha(self.projection_revision, "projection_revision")
        _sha(self.source_cut_fingerprint, "source_cut_fingerprint")
        _sha(self.dataset_snapshot_fingerprint, "dataset_snapshot_fingerprint")
        _sha(self.evaluation_context_fingerprint, "evaluation_context_fingerprint")
        if (
            type(self.representation_schema_version) is not int
            or self.representation_schema_version != REPRESENTATION_SCHEMA_VERSION
        ):
            raise ValueError("advisory representation schema is unsupported")
        for name in ("operator_features", "topology_features", "output_features"):
            values = getattr(self, name)
            if (
                not values
                or values != tuple(sorted(set(values)))
                or any(not isinstance(item, str) or not item for item in values)
            ):
                raise ValueError(f"{name} must be non-empty, canonical, and unique")
        if self.parameter_features != tuple(sorted(set(self.parameter_features))) or len(
            {item.key for item in self.parameter_features}
        ) != len(self.parameter_features):
            raise ValueError("parameter_features must be canonical and unique")

    @property
    def representation_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "representation_schema_version": self.representation_schema_version,
            "source_ref": self.source_ref.to_dict(),
            "projection_revision": self.projection_revision,
            "source_cut_fingerprint": self.source_cut_fingerprint,
            "operator_features": list(self.operator_features),
            "topology_features": list(self.topology_features),
            "parameter_features": [item.to_dict() for item in self.parameter_features],
            "output_features": list(self.output_features),
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "evaluation_context_fingerprint": self.evaluation_context_fingerprint,
        }
        if include_fingerprint:
            payload["representation_fingerprint"] = self.representation_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchAdvisoryRepresentationV1:
        expected = {
            "representation_schema_version",
            "source_ref",
            "projection_revision",
            "source_cut_fingerprint",
            "operator_features",
            "topology_features",
            "parameter_features",
            "output_features",
            "dataset_snapshot_fingerprint",
            "evaluation_context_fingerprint",
            "representation_fingerprint",
        }
        if set(payload) != expected:
            raise ValueError("advisory representation fields are invalid")
        fields = dict(payload)
        fingerprint = fields.pop("representation_fingerprint")
        for name in ("source_ref",):
            if not isinstance(fields[name], Mapping):
                raise ValueError(f"{name} must be an object")
        for name in ("operator_features", "topology_features", "parameter_features", "output_features"):
            if not isinstance(fields[name], list):
                raise ValueError(f"{name} must be an array")
        if any(not isinstance(item, Mapping) for item in cast(list[object], fields["parameter_features"])):
            raise ValueError("parameter_features entries must be objects")
        result = cls(
            OnlyResearchAdvisorySourceRefV1.from_dict(cast(Mapping[str, object], fields["source_ref"])),
            cast(str, fields["projection_revision"]),
            cast(str, fields["source_cut_fingerprint"]),
            tuple(cast(list[str], fields["operator_features"])),
            tuple(cast(list[str], fields["topology_features"])),
            tuple(
                OnlyResearchAdvisoryParameterV1.from_dict(cast(Mapping[str, object], item))
                for item in cast(list[object], fields["parameter_features"])
            ),
            tuple(cast(list[str], fields["output_features"])),
            cast(str, fields["dataset_snapshot_fingerprint"]),
            cast(str, fields["evaluation_context_fingerprint"]),
            cast(int, fields["representation_schema_version"]),
        )
        if fingerprint != result.representation_fingerprint or result.to_dict() != dict(payload):
            raise ValueError("advisory representation fingerprint differs")
        return result


def _operator(definition: OnlyCalculationDefinition) -> str:
    return "|".join(
        (
            str(definition.kind.value),
            str(definition.type_id),
            str(definition.semantic_version),
        )
    )


def _parameter(key: str, value: OnlyCalculationScalar) -> OnlyResearchAdvisoryParameterV1:
    kind = (
        "NONE"
        if value is None
        else "BOOLEAN"
        if isinstance(value, bool)
        else "INTEGER"
        if isinstance(value, int)
        else "DECIMAL"
        if isinstance(value, Decimal)
        else "STRING"
    )
    return OnlyResearchAdvisoryParameterV1(key, kind, only_canonical_json(value))


def only_build_research_advisory_representation(
    *,
    subject: OnlyExactEvaluationIntentSubjectV1,
    graph: OnlyCalculationGraphDefinition,
    specification: OnlyResearchSpecification,
    source_ref: OnlyResearchAdvisorySourceRefV1,
    projection_revision: str,
    source_cut_fingerprint: str,
) -> OnlyResearchAdvisoryRepresentationV1:
    """Derive retrieval-only features from already verified canonical facts."""
    if graph.fingerprint != subject.graph_fingerprint:
        raise ValueError("advisory Graph does not bind the exact Evaluation Subject")
    if (
        specification.specification_fingerprint != subject.specification_fingerprint
        or specification.dataset_snapshot_fingerprint != subject.dataset_snapshot_fingerprint
        or specification.evidence is None
    ):
        raise ValueError("advisory Specification does not bind the exact Evaluation Subject")
    nodes = {node.fingerprint: node for node in graph.ordered_nodes}
    selected = nodes.get(subject.candidate_node_fingerprint)
    if selected is None:
        raise ValueError("advisory candidate node is absent from the verified Graph")
    outputs = {item.name: item for item in selected.definition.outputs}
    output = outputs.get(subject.output_name)
    if output is None:
        raise ValueError("advisory output is absent from the verified Graph")

    operators = tuple(sorted({_operator(node.definition) for node in nodes.values()}))
    ordinals = {node.fingerprint: index for index, node in enumerate(graph.ordered_nodes)}
    topology: set[str] = set()
    parameters: list[OnlyResearchAdvisoryParameterV1] = []
    for node in graph.ordered_nodes:
        operator = _operator(node.definition)
        parameters.extend(
            _parameter(f"n{ordinals[node.fingerprint]}|{operator}|{name}", value)
            for name, value in sorted(node.definition.parameters.items())
        )
        for name, binding in sorted(node.definition.input_bindings.items()):
            parent = (
                "SOURCE:" + binding.source
                if binding.source is not None
                else f"n{ordinals[cast(str, binding.node_fingerprint)]}|"
                + _operator(nodes[cast(str, binding.node_fingerprint)].definition)
            )
            topology.add(f"n{ordinals[node.fingerprint]}|{operator}|{name}|{parent}|{binding.output_name}")

    candidate_id = specification.evidence.candidate_calculation_id
    calculations = {item.calculation_id: item for item in specification.calculations}
    contexts: list[object] = []
    for item in specification.statistics:
        if item.feature.calculation_id != candidate_id:
            continue
        target = calculations.get(item.target.calculation_id)
        if target is None:
            raise ValueError("advisory Statistics target is absent from the verified Specification")
        contexts.append(
            {
                "target_graph_template": target.graph_template.to_dict(),
                "target_node": item.target.template_node_id,
                "target_output": item.target.output_name,
                "statistics_definition": item.definition.to_dict(),
                "expansion": item.expansion,
            }
        )
    if not contexts:
        raise ValueError("advisory candidate has no verified evaluation context")
    evaluation_context = only_canonical_fingerprint(
        {
            "dataset_snapshot_fingerprint": subject.dataset_snapshot_fingerprint,
            "catalog_generation_fingerprint": subject.catalog_generation_fingerprint,
            "runtime_generation_fingerprint": subject.runtime_generation_fingerprint,
            "authoring_generation_fingerprint": subject.authoring_generation_fingerprint,
            "scientific_evidence_contract": specification.evidence.to_dict(),
            "statistics": contexts,
        }
    )
    output_features = tuple(
        sorted(
            {
                f"operator:{_operator(selected.definition)}",
                f"name:{output.name}",
                f"data_type:{output.data_type.value}",
                f"nullable:{str(output.nullable).lower()}",
                f"dimensions:{','.join(output.dimensions)}",
                f"semantic_type:{output.semantic_type}",
                f"unit:{output.unit or ''}",
            }
        )
    )
    return OnlyResearchAdvisoryRepresentationV1(
        source_ref,
        projection_revision,
        source_cut_fingerprint,
        operators,
        tuple(sorted(topology)),
        tuple(sorted(parameters)),
        output_features,
        subject.dataset_snapshot_fingerprint,
        evaluation_context,
    )


@dataclass(frozen=True, slots=True)
class OnlyResearchAdvisoryIndexV1:
    projection_revision: str
    source_cut_fingerprint: str
    representations: tuple[OnlyResearchAdvisoryRepresentationV1, ...]
    index_schema_version: int = INDEX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _sha(self.projection_revision, "projection_revision")
        _sha(self.source_cut_fingerprint, "source_cut_fingerprint")
        if type(self.index_schema_version) is not int or self.index_schema_version != INDEX_SCHEMA_VERSION:
            raise ValueError("advisory index schema is unsupported")
        expected = tuple(sorted(self.representations, key=lambda item: item.representation_fingerprint))
        if self.representations != expected or len({item.representation_fingerprint for item in expected}) != len(
            expected
        ):
            raise ValueError("advisory representations must be canonical and unique")
        if len({item.source_ref for item in expected}) != len(expected):
            raise ValueError("one advisory source cannot have conflicting representations")
        if any(
            item.projection_revision != self.projection_revision
            or item.source_cut_fingerprint != self.source_cut_fingerprint
            for item in expected
        ):
            raise ValueError("advisory representations mix projection revisions or source cuts")

    @property
    def index_build_revision(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "index_schema_version": self.index_schema_version,
            "projection_revision": self.projection_revision,
            "source_cut_fingerprint": self.source_cut_fingerprint,
            "representations": [item.to_dict() for item in self.representations],
        }
        if include_fingerprint:
            payload["index_build_revision"] = self.index_build_revision
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchAdvisoryIndexV1:
        expected = {
            "index_schema_version",
            "projection_revision",
            "source_cut_fingerprint",
            "representations",
            "index_build_revision",
        }
        raw = payload.get("representations")
        if set(payload) != expected or not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
            raise ValueError("advisory index fields are invalid")
        result = cls(
            cast(str, payload["projection_revision"]),
            cast(str, payload["source_cut_fingerprint"]),
            tuple(OnlyResearchAdvisoryRepresentationV1.from_dict(cast(Mapping[str, object], item)) for item in raw),
            cast(int, payload["index_schema_version"]),
        )
        if payload["index_build_revision"] != result.index_build_revision or result.to_dict() != dict(payload):
            raise ValueError("advisory index build revision differs")
        return result


def only_build_research_advisory_index(
    projection_revision: str,
    source_cut_fingerprint: str,
    representations: tuple[OnlyResearchAdvisoryRepresentationV1, ...],
) -> OnlyResearchAdvisoryIndexV1:
    return OnlyResearchAdvisoryIndexV1(
        projection_revision,
        source_cut_fingerprint,
        tuple(sorted(representations, key=lambda item: item.representation_fingerprint)),
    )


@dataclass(frozen=True, slots=True)
class OnlyVerifiedResearchAdvisorySnapshotV1:
    """Request-scoped verified advisory state; never a source-truth authority."""

    projection: OnlyExperimentMemoryProjectionV1
    representations: tuple[OnlyResearchAdvisoryRepresentationV1, ...]
    index: OnlyResearchAdvisoryIndexV1
    representation_by_source_ref: Mapping[OnlyResearchAdvisorySourceRefV1, OnlyResearchAdvisoryRepresentationV1]

    def __post_init__(self) -> None:
        if self.projection.revision_fingerprint != self.index.projection_revision:
            raise ValueError("advisory snapshot projection revision differs")
        source_cut = self.projection.source_manifest.manifest_fingerprint
        if source_cut != self.index.source_cut_fingerprint:
            raise ValueError("advisory snapshot source cut differs")
        if self.representations != self.index.representations:
            raise ValueError("advisory snapshot representations differ")
        expected = {item.source_ref: item for item in self.representations}
        if dict(self.representation_by_source_ref) != expected:
            raise ValueError("advisory snapshot source map differs")
        object.__setattr__(self, "representation_by_source_ref", MappingProxyType(expected))

    @property
    def projection_revision(self) -> str:
        return self.index.projection_revision

    @property
    def source_cut_fingerprint(self) -> str:
        return self.index.source_cut_fingerprint

    @property
    def index_build_revision(self) -> str:
        return self.index.index_build_revision

    def load_representation_verified(
        self,
        source_ref: OnlyResearchAdvisorySourceRefV1,
        projection_revision: str,
        representation_schema_version: int,
    ) -> OnlyResearchAdvisoryRepresentationV1:
        if projection_revision != self.projection_revision:
            raise ValueError("advisory source revision differs")
        if representation_schema_version != REPRESENTATION_SCHEMA_VERSION:
            raise ValueError("advisory representation schema is unsupported")
        try:
            return self.representation_by_source_ref[source_ref]
        except KeyError as exc:
            raise ValueError("advisory source is missing or ambiguous") from exc


@dataclass(frozen=True, slots=True)
class OnlyNearDuplicateThresholdPolicyV1:
    policy_id: str
    policy_version: str
    minimum_retrieval_score: Decimal
    advisory_similarity_score: Decimal
    maximum_results: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        _text(self.policy_id, "threshold policy_id")
        _text(self.policy_version, "threshold policy_version")
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or not self.minimum_retrieval_score.is_finite()
            or not self.advisory_similarity_score.is_finite()
            or not Decimal(0) <= self.minimum_retrieval_score <= self.advisory_similarity_score <= Decimal(1)
            or type(self.maximum_results) is not int
            or not 1 <= self.maximum_results <= 100
        ):
            raise ValueError("near-duplicate threshold policy is invalid")

    @property
    def policy_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "minimum_retrieval_score": _decimal_text(self.minimum_retrieval_score),
            "advisory_similarity_score": _decimal_text(self.advisory_similarity_score),
            "maximum_results": self.maximum_results,
        }
        if include_fingerprint:
            payload["policy_fingerprint"] = self.policy_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNearDuplicateThresholdPolicyV1:
        expected = {
            "schema_version",
            "policy_id",
            "policy_version",
            "minimum_retrieval_score",
            "advisory_similarity_score",
            "maximum_results",
            "policy_fingerprint",
        }
        if set(payload) != expected:
            raise ValueError("near-duplicate threshold policy fields are invalid")
        result = cls(
            cast(str, payload["policy_id"]),
            cast(str, payload["policy_version"]),
            _decimal(payload["minimum_retrieval_score"], "minimum_retrieval_score"),
            _decimal(payload["advisory_similarity_score"], "advisory_similarity_score"),
            cast(int, payload["maximum_results"]),
            cast(int, payload["schema_version"]),
        )
        if payload["policy_fingerprint"] != result.policy_fingerprint or result.to_dict() != dict(payload):
            raise ValueError("near-duplicate threshold policy fingerprint differs")
        return result


@dataclass(frozen=True, slots=True)
class OnlyNearDuplicateQueryV1:
    representation_fingerprint: str
    projection_revision: str
    source_cut_fingerprint: str
    index_build_revision: str
    threshold_policy_fingerprint: str
    requested_result_limit: int
    retrieval_algorithm_id: str = STRUCTURED_ALGORITHM_ID
    retrieval_algorithm_version: str = STRUCTURED_ALGORITHM_VERSION
    query_schema_version: int = QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "representation_fingerprint",
            "projection_revision",
            "source_cut_fingerprint",
            "index_build_revision",
            "threshold_policy_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if (
            type(self.query_schema_version) is not int
            or self.query_schema_version != QUERY_SCHEMA_VERSION
            or self.retrieval_algorithm_id != STRUCTURED_ALGORITHM_ID
            or self.retrieval_algorithm_version != STRUCTURED_ALGORITHM_VERSION
            or type(self.requested_result_limit) is not int
            or not 1 <= self.requested_result_limit <= 100
        ):
            raise ValueError("near-duplicate query is unsupported or invalid")

    @property
    def query_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload = {
            "query_schema_version": self.query_schema_version,
            "representation_fingerprint": self.representation_fingerprint,
            "projection_revision": self.projection_revision,
            "source_cut_fingerprint": self.source_cut_fingerprint,
            "index_build_revision": self.index_build_revision,
            "retrieval_algorithm_id": self.retrieval_algorithm_id,
            "retrieval_algorithm_version": self.retrieval_algorithm_version,
            "threshold_policy_fingerprint": self.threshold_policy_fingerprint,
            "requested_result_limit": self.requested_result_limit,
        }
        if include_fingerprint:
            payload["query_fingerprint"] = self.query_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNearDuplicateQueryV1:
        expected = {
            "query_schema_version",
            "representation_fingerprint",
            "projection_revision",
            "source_cut_fingerprint",
            "index_build_revision",
            "retrieval_algorithm_id",
            "retrieval_algorithm_version",
            "threshold_policy_fingerprint",
            "requested_result_limit",
            "query_fingerprint",
        }
        if set(payload) != expected:
            raise ValueError("near-duplicate query fields are invalid")
        result = cls(
            cast(str, payload["representation_fingerprint"]),
            cast(str, payload["projection_revision"]),
            cast(str, payload["source_cut_fingerprint"]),
            cast(str, payload["index_build_revision"]),
            cast(str, payload["threshold_policy_fingerprint"]),
            cast(int, payload["requested_result_limit"]),
            cast(str, payload["retrieval_algorithm_id"]),
            cast(str, payload["retrieval_algorithm_version"]),
            cast(int, payload["query_schema_version"]),
        )
        if payload["query_fingerprint"] != result.query_fingerprint or result.to_dict() != dict(payload):
            raise ValueError("near-duplicate query fingerprint differs")
        return result


class OnlyNearDuplicateAdvisoryContextTier(StrEnum):
    RETRIEVABLE = "RETRIEVABLE"
    COMPARABLE = "COMPARABLE"
    ADVISORY_SIMILAR = "ADVISORY_SIMILAR"


class OnlyNearDuplicateResultStatus(StrEnum):
    ADVISORY_OK = "ADVISORY_OK"
    ADVISORY_UNAVAILABLE = "ADVISORY_UNAVAILABLE"
    ADVISORY_PARTIAL = "ADVISORY_PARTIAL"
    ADVISORY_UNSUPPORTED = "ADVISORY_UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class OnlyNearDuplicateMatchV1:
    source_kind: str
    native_locator: str
    source_identity: str
    source_revision: str
    score: Decimal
    context_tiers: tuple[OnlyNearDuplicateAdvisoryContextTier, ...]
    representation_fingerprint: str
    same: tuple[str, ...]
    different: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.source_kind, "source_kind")
        _text(self.native_locator, "native_locator")
        _text(self.source_identity, "source_identity")
        _sha(self.source_revision, "source_revision")
        _sha(self.representation_fingerprint, "representation_fingerprint")
        if not self.score.is_finite() or not Decimal(0) <= self.score <= Decimal(1):
            raise ValueError("near-duplicate score is invalid")
        if (
            not self.context_tiers
            or any(not isinstance(item, OnlyNearDuplicateAdvisoryContextTier) for item in self.context_tiers)
            or self.context_tiers != tuple(sorted(set(self.context_tiers), key=lambda item: item.value))
            or self.same != tuple(sorted(set(self.same)))
            or self.different != tuple(sorted(set(self.different)))
            or set(self.same) & set(self.different)
            or set(self.same) | set(self.different) != _COMPARISON_DIMENSIONS
            or any(not isinstance(item, str) or not item for item in (*self.same, *self.different))
            or OnlyNearDuplicateAdvisoryContextTier.RETRIEVABLE not in self.context_tiers
            or (
                OnlyNearDuplicateAdvisoryContextTier.COMPARABLE in self.context_tiers
                and not {"DATASET", "EVALUATION_CONTEXT"}.issubset(self.same)
            )
        ):
            raise ValueError("near-duplicate explanation is not canonical")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind,
            "native_locator": self.native_locator,
            "source_identity": self.source_identity,
            "source_revision": self.source_revision,
            "score": _decimal_text(self.score),
            "context_tiers": [item.value for item in self.context_tiers],
            "representation_fingerprint": self.representation_fingerprint,
            "same": list(self.same),
            "different": list(self.different),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNearDuplicateMatchV1:
        expected = {
            "source_kind",
            "native_locator",
            "source_identity",
            "source_revision",
            "score",
            "context_tiers",
            "representation_fingerprint",
            "same",
            "different",
        }
        tiers, same, different = payload.get("context_tiers"), payload.get("same"), payload.get("different")
        if (
            set(payload) != expected
            or not isinstance(tiers, list)
            or not isinstance(same, list)
            or not isinstance(different, list)
        ):
            raise ValueError("near-duplicate match fields are invalid")
        try:
            result = cls(
                cast(str, payload["source_kind"]),
                cast(str, payload["native_locator"]),
                cast(str, payload["source_identity"]),
                cast(str, payload["source_revision"]),
                _decimal(payload["score"], "score"),
                tuple(OnlyNearDuplicateAdvisoryContextTier(cast(str, item)) for item in tiers),
                cast(str, payload["representation_fingerprint"]),
                tuple(cast(list[str], same)),
                tuple(cast(list[str], different)),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("near-duplicate match is invalid") from exc
        if result.to_dict() != dict(payload):
            raise ValueError("near-duplicate match is not canonical")
        return result


@dataclass(frozen=True, slots=True)
class OnlyNearDuplicateResultV1:
    query_fingerprint: str
    projection_revision: str
    source_cut_fingerprint: str
    representation_schema_version: int
    retrieval_algorithm_id: str
    retrieval_algorithm_version: str
    threshold_policy_id: str
    threshold_policy_version: str
    threshold_policy_fingerprint: str
    index_build_revision: str
    status: OnlyNearDuplicateResultStatus
    matches: tuple[OnlyNearDuplicateMatchV1, ...]
    failure_code: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    model_content_fingerprint: str | None = None
    result_schema_version: int = RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "query_fingerprint",
            "projection_revision",
            "source_cut_fingerprint",
            "threshold_policy_fingerprint",
            "index_build_revision",
        ):
            _sha(getattr(self, name), name)
        if (
            type(self.result_schema_version) is not int
            or self.result_schema_version != RESULT_SCHEMA_VERSION
            or type(self.representation_schema_version) is not int
            or self.representation_schema_version != REPRESENTATION_SCHEMA_VERSION
            or self.retrieval_algorithm_id != STRUCTURED_ALGORITHM_ID
            or self.retrieval_algorithm_version != STRUCTURED_ALGORITHM_VERSION
        ):
            raise ValueError("near-duplicate result schema is unsupported")
        _text(self.threshold_policy_id, "threshold_policy_id")
        _text(self.threshold_policy_version, "threshold_policy_version")
        if not isinstance(self.status, OnlyNearDuplicateResultStatus):
            raise ValueError("near-duplicate result status is invalid")
        if self.status is OnlyNearDuplicateResultStatus.ADVISORY_OK and self.failure_code is not None:
            raise ValueError("successful advisory result cannot carry a failure code")
        if self.status is not OnlyNearDuplicateResultStatus.ADVISORY_OK and (
            not isinstance(self.failure_code, str) or not self.failure_code
        ):
            raise ValueError("non-success advisory result requires a failure code")
        if (
            self.status
            in {
                OnlyNearDuplicateResultStatus.ADVISORY_UNAVAILABLE,
                OnlyNearDuplicateResultStatus.ADVISORY_UNSUPPORTED,
            }
            and self.matches
        ):
            raise ValueError("unavailable or unsupported advisory result cannot carry matches")
        if self.matches != tuple(
            sorted(
                self.matches,
                key=lambda item: (-item.score, item.source_kind, item.native_locator, item.source_identity),
            )
        ):
            raise ValueError("near-duplicate matches are not deterministically ordered")
        match_sources = tuple(
            (item.source_kind, item.native_locator, item.source_identity, item.source_revision) for item in self.matches
        )
        if len(match_sources) != len(set(match_sources)):
            raise ValueError("near-duplicate matches contain duplicate sources")
        if any(value is not None for value in (self.model_id, self.model_version, self.model_content_fingerprint)):
            raise ValueError("STRUCTURED_NEAR_DUPLICATE_V1 does not accept model identity")

    @property
    def result_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "result_schema_version": self.result_schema_version,
            "query_fingerprint": self.query_fingerprint,
            "projection_revision": self.projection_revision,
            "source_cut_fingerprint": self.source_cut_fingerprint,
            "representation_schema_version": self.representation_schema_version,
            "retrieval_algorithm_id": self.retrieval_algorithm_id,
            "retrieval_algorithm_version": self.retrieval_algorithm_version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "model_content_fingerprint": self.model_content_fingerprint,
            "threshold_policy_id": self.threshold_policy_id,
            "threshold_policy_version": self.threshold_policy_version,
            "threshold_policy_fingerprint": self.threshold_policy_fingerprint,
            "index_build_revision": self.index_build_revision,
            "status": self.status.value,
            "matches": [item.to_dict() for item in self.matches],
            "failure_code": self.failure_code,
        }
        if include_fingerprint:
            payload["result_fingerprint"] = self.result_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNearDuplicateResultV1:
        expected = {
            "result_schema_version",
            "query_fingerprint",
            "projection_revision",
            "source_cut_fingerprint",
            "representation_schema_version",
            "retrieval_algorithm_id",
            "retrieval_algorithm_version",
            "model_id",
            "model_version",
            "model_content_fingerprint",
            "threshold_policy_id",
            "threshold_policy_version",
            "threshold_policy_fingerprint",
            "index_build_revision",
            "status",
            "matches",
            "failure_code",
            "result_fingerprint",
        }
        raw = payload.get("matches")
        if set(payload) != expected or not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
            raise ValueError("near-duplicate result fields are invalid")
        try:
            result = cls(
                cast(str, payload["query_fingerprint"]),
                cast(str, payload["projection_revision"]),
                cast(str, payload["source_cut_fingerprint"]),
                cast(int, payload["representation_schema_version"]),
                cast(str, payload["retrieval_algorithm_id"]),
                cast(str, payload["retrieval_algorithm_version"]),
                cast(str, payload["threshold_policy_id"]),
                cast(str, payload["threshold_policy_version"]),
                cast(str, payload["threshold_policy_fingerprint"]),
                cast(str, payload["index_build_revision"]),
                OnlyNearDuplicateResultStatus(cast(str, payload["status"])),
                tuple(OnlyNearDuplicateMatchV1.from_dict(cast(Mapping[str, object], item)) for item in raw),
                cast(str | None, payload["failure_code"]),
                cast(str | None, payload["model_id"]),
                cast(str | None, payload["model_version"]),
                cast(str | None, payload["model_content_fingerprint"]),
                cast(int, payload["result_schema_version"]),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("near-duplicate result is invalid") from exc
        if payload["result_fingerprint"] != result.result_fingerprint or result.to_dict() != dict(payload):
            raise ValueError("near-duplicate result fingerprint differs")
        return result


class OnlyResearchAdvisorySourceVerifier(Protocol):
    def load_representation_verified(
        self,
        source_ref: OnlyResearchAdvisorySourceRefV1,
        projection_revision: str,
        representation_schema_version: int,
    ) -> OnlyResearchAdvisoryRepresentationV1: ...


class OnlyResearchAdvisoryUnavailableError(RuntimeError):
    pass


class _OnlyResearchAdvisoryCalculationManifest(Protocol):
    calculation_fingerprint: str
    calculation_graph_fingerprint: str
    calculation_graph: OnlyCalculationGraphDefinition


class _OnlyResearchAdvisoryCalculationResult(Protocol):
    manifest: _OnlyResearchAdvisoryCalculationManifest


class OnlyResearchAdvisoryCalculationResultReader(Protocol):
    def load_verified(self, calculation_fingerprint: str) -> _OnlyResearchAdvisoryCalculationResult: ...


class OnlyResearchAdvisoryReferenceReaders(Protocol):
    def for_observations(
        self, observations: tuple[OnlySourceObservationV1, ...]
    ) -> Callable[[str, str], Mapping[str, object]]: ...


class OnlyExperimentMemoryAdvisoryProjectionBuilder:
    """Rebuild and verify disposable advice from frozen owning source facts."""

    def __init__(
        self,
        revisions: OnlyExperimentMemoryRevisionStore,
        source_readers: Mapping[str, OnlyMemoryCutReader],
        reference_readers: OnlyResearchAdvisoryReferenceReaders,
        calculation_results: OnlyResearchAdvisoryCalculationResultReader,
    ) -> None:
        if set(source_readers) != set(MANDATORY_FAMILIES):
            raise ValueError("advisory source readers are incomplete")
        self._revisions = revisions
        self._sources = dict(source_readers)
        self._references = reference_readers
        self._calculations = calculation_results

    def build_index(self, projection_revision: str) -> OnlyResearchAdvisoryIndexV1:
        projection, representations = self._load(projection_revision)
        return only_build_research_advisory_index(
            projection.revision_fingerprint,
            projection.source_manifest.manifest_fingerprint,
            representations,
        )

    def load_snapshot_verified(self, projection_revision: str) -> OnlyVerifiedResearchAdvisorySnapshotV1:
        projection, representations = self._load(projection_revision)
        return self._snapshot(projection, representations)

    def load_active_snapshot_verified(self) -> OnlyVerifiedResearchAdvisorySnapshotV1:
        projection = self._revisions.load_active_verified()
        return self._snapshot(projection, self._representations_for_projection(projection))

    def load_representation_verified(
        self,
        source_ref: OnlyResearchAdvisorySourceRefV1,
        projection_revision: str,
        representation_schema_version: int,
    ) -> OnlyResearchAdvisoryRepresentationV1:
        if representation_schema_version != REPRESENTATION_SCHEMA_VERSION:
            raise ValueError("advisory representation schema is unsupported")
        _, representations = self._load(projection_revision)
        matches = tuple(item for item in representations if item.source_ref == source_ref)
        if len(matches) != 1:
            raise ValueError("advisory source is missing or ambiguous")
        return matches[0]

    def _load(
        self, projection_revision: str
    ) -> tuple[OnlyExperimentMemoryProjectionV1, tuple[OnlyResearchAdvisoryRepresentationV1, ...]]:
        return self._load_projection(self._revisions.load_verified(projection_revision))

    def _load_projection(
        self, projection: OnlyExperimentMemoryProjectionV1
    ) -> tuple[OnlyExperimentMemoryProjectionV1, tuple[OnlyResearchAdvisoryRepresentationV1, ...]]:
        try:
            observations = only_load_cut_observations(projection.source_manifest, self._sources)
            exact = self._references.for_observations(observations)
        except OnlyMemoryProjectionError as exc:
            if str(exc) in {"SOURCE_OBSERVATION_UNAVAILABLE", "REFERENCE_AUTHORITY_UNAVAILABLE"}:
                raise OnlyResearchAdvisoryUnavailableError(str(exc)) from exc
            raise ValueError("advisory projection source verification failed") from exc
        by_ref = {
            (item.source_family, item.cut_fingerprint, item.locator, item.identity, item.content_fingerprint): item
            for item in observations
        }
        return projection, self._representations_for_projection(projection, by_ref=by_ref, exact=exact)

    def _representations_for_projection(
        self,
        projection: OnlyExperimentMemoryProjectionV1,
        *,
        by_ref: Mapping[tuple[str, str, str, str, str], OnlySourceObservationV1] | None = None,
        exact: Callable[[str, str], Mapping[str, object]] | None = None,
    ) -> tuple[OnlyResearchAdvisoryRepresentationV1, ...]:
        if by_ref is None or exact is None:
            try:
                observations = only_load_cut_observations(projection.source_manifest, self._sources)
                exact = self._references.for_observations(observations)
            except OnlyMemoryProjectionError as exc:
                if str(exc) in {"SOURCE_OBSERVATION_UNAVAILABLE", "REFERENCE_AUTHORITY_UNAVAILABLE"}:
                    raise OnlyResearchAdvisoryUnavailableError(str(exc)) from exc
                raise ValueError("advisory projection source verification failed") from exc
            by_ref = {
                (item.source_family, item.cut_fingerprint, item.locator, item.identity, item.content_fingerprint): item
                for item in observations
            }
        representations: list[OnlyResearchAdvisoryRepresentationV1] = []
        for record in projection.records:
            if record.kind == "EvaluationProjectionRecord":
                representations.extend(self._representations(projection, record, by_ref, exact))
        return tuple(sorted(representations, key=lambda item: item.representation_fingerprint))

    @staticmethod
    def _snapshot(
        projection: OnlyExperimentMemoryProjectionV1,
        representations: tuple[OnlyResearchAdvisoryRepresentationV1, ...],
    ) -> OnlyVerifiedResearchAdvisorySnapshotV1:
        index = only_build_research_advisory_index(
            projection.revision_fingerprint,
            projection.source_manifest.manifest_fingerprint,
            representations,
        )
        return OnlyVerifiedResearchAdvisorySnapshotV1(
            projection,
            index.representations,
            index,
            {item.source_ref: item for item in index.representations},
        )

    def _representations(
        self,
        projection: OnlyExperimentMemoryProjectionV1,
        record: OnlyMemoryProjectionRecordV1,
        by_ref: Mapping[tuple[str, str, str, str, str], OnlySourceObservationV1],
        exact: Callable[[str, str], Mapping[str, object]],
    ) -> tuple[OnlyResearchAdvisoryRepresentationV1, ...]:
        facets = record.facets
        result_ref = self._one_record_ref(
            record,
            "RESEARCH_RESULT",
            facets.get("research_result_locator"),
            facets.get("research_result_fingerprint"),
        )
        result = self._observation(result_ref, by_ref)
        graph = self._graph(result, facets.get("graph_fingerprint"))
        raw_statistics = facets.get("statistics_references")
        closures = facets.get("run_evaluation_closures")
        if not isinstance(raw_statistics, list) or not raw_statistics or not isinstance(closures, list) or not closures:
            raise ValueError("advisory evaluation projection is incomplete")
        self._verify_result_facets(record, result, facets, raw_statistics, by_ref)
        try:
            dataset = exact("DATASET_SNAPSHOT", cast(str, facets.get("dataset_snapshot_fingerprint")))
            graph_identity = exact("CALCULATION_GRAPH", graph.fingerprint)
        except OnlyMemoryProjectionError as exc:
            raise OnlyResearchAdvisoryUnavailableError(str(exc)) from exc
        if (
            dataset.get("snapshot_fingerprint") != facets.get("dataset_snapshot_fingerprint")
            or graph_identity.get("graph_fingerprint") != graph.fingerprint
        ):
            raise ValueError("advisory exact reference differs from the projection")
        output: list[OnlyResearchAdvisoryRepresentationV1] = []
        for raw in closures:
            if not isinstance(raw, Mapping):
                raise ValueError("advisory Run closure is invalid")
            run_ref = self._memory_ref(raw.get("run_source_ref"))
            if run_ref not in record.source_refs:
                raise ValueError("advisory Run relation is absent from the projection")
            run = self._observation(run_ref, by_ref)
            specification = self._specification(run, raw.get("specification_fingerprint"))
            self._verify_run_closure(run, raw)
            try:
                verified_specification = exact("RESEARCH_SPECIFICATION", specification.specification_fingerprint)
                binding = exact("RUNTIME_WORK_BINDING", cast(str, raw.get("run_id")))
                authoring = raw.get("authoring_generation_fingerprint")
                if isinstance(authoring, str):
                    exact("AUTHORING_GENERATION", authoring)
            except OnlyMemoryProjectionError as exc:
                raise OnlyResearchAdvisoryUnavailableError(str(exc)) from exc
            if (
                verified_specification != specification.to_dict()
                or binding.get("work_id") != raw.get("run_id")
                or binding.get("runtime_generation_fingerprint") != raw.get("runtime_generation_fingerprint")
                or binding.get("catalog_generation_fingerprint") != raw.get("catalog_generation_fingerprint")
            ):
                raise ValueError("advisory Run exact references differ from the projection")
            subject = OnlyExactEvaluationHistorySelectorV1(
                OnlyExactSemanticHistorySelectorV1(
                    cast(str, facets.get("graph_fingerprint")),
                    cast(str, facets.get("candidate_node_fingerprint")),
                    cast(str, facets.get("output_name")),
                ),
                cast(str, facets.get("candidate_fingerprint")),
                cast(str, facets.get("dataset_snapshot_fingerprint")),
                specification.specification_fingerprint,
                cast(str, facets.get("research_result_locator")),
                cast(str, raw.get("catalog_generation_fingerprint")),
                cast(str, raw.get("runtime_generation_fingerprint")),
                cast(str | None, raw.get("authoring_generation_fingerprint")),
                tuple(
                    OnlyExactStatisticsReferenceV1(
                        cast(str, item["statistics_fingerprint"]),
                        cast(str, item["statistics_result_fingerprint"]),
                    )
                    for item in raw_statistics
                ),
            ).intent_subject
            source_ref = self._entry_ref(result_ref, run_ref, subject)
            output.append(
                only_build_research_advisory_representation(
                    subject=subject,
                    graph=graph,
                    specification=specification,
                    source_ref=source_ref,
                    projection_revision=projection.revision_fingerprint,
                    source_cut_fingerprint=projection.source_manifest.manifest_fingerprint,
                )
            )
        return tuple(output)

    @staticmethod
    def _verify_result_facets(
        record: OnlyMemoryProjectionRecordV1,
        result: OnlySourceObservationV1,
        facets: Mapping[str, object],
        statistics: list[object],
        by_ref: Mapping[tuple[str, str, str, str, str], OnlySourceObservationV1],
    ) -> None:
        payload = result.canonical_payload
        plan = payload.get("plan")
        if not isinstance(plan, Mapping):
            raise ValueError("advisory Result plan is unavailable")
        candidates = plan.get("candidates")
        series = (*cast(list[object], plan.get("published_series", [])), *cast(list[object], plan.get("signals", [])))
        candidate = (
            tuple(
                item
                for item in cast(list[object], candidates)
                if isinstance(item, Mapping)
                and item.get("candidate_fingerprint") == facets.get("candidate_fingerprint")
                and item.get("graph_fingerprint") == facets.get("graph_fingerprint")
            )
            if isinstance(candidates, list)
            else ()
        )
        output = tuple(
            item
            for item in series
            if isinstance(item, Mapping)
            and item.get("candidate_fingerprint") == facets.get("candidate_fingerprint")
            and item.get("node_fingerprint") == facets.get("candidate_node_fingerprint")
            and item.get("output_name") == facets.get("output_name")
        )
        available_statistics = payload.get("statistics_results")
        statistic_fingerprints = {
            item.get("statistics_fingerprint") for item in statistics if isinstance(item, Mapping)
        }
        candidate_statistics = candidate[0].get("statistics_fingerprints") if candidate else None
        for item in statistics:
            if not isinstance(item, Mapping):
                raise ValueError("advisory Statistics reference is invalid")
            matches = tuple(
                ref
                for ref in record.source_refs
                if ref.source_family
                in {"RESEARCH_STATISTICS", "RESEARCH_FACTOR_PAIR_STATISTICS", "RESEARCH_SUMMARY_STATISTICS"}
                and ref.identity == item.get("statistics_result_fingerprint")
            )
            if len(matches) != 1:
                raise ValueError("advisory Statistics relation is incomplete")
            observation = OnlyExperimentMemoryAdvisoryProjectionBuilder._observation(matches[0], by_ref)
            if observation.canonical_payload.get("statistics_fingerprint") != item.get(
                "statistics_fingerprint"
            ) or observation.canonical_payload.get("statistics_result_fingerprint") != item.get(
                "statistics_result_fingerprint"
            ):
                raise ValueError("advisory Statistics source differs from the Result")
        if (
            payload.get("dataset_snapshot_fingerprint") != facets.get("dataset_snapshot_fingerprint")
            or len(candidate) != 1
            or len(output) != 1
            or not isinstance(available_statistics, list)
            or any(item not in available_statistics for item in statistics)
            or not isinstance(candidate_statistics, list)
            or set(candidate_statistics) != statistic_fingerprints
        ):
            raise ValueError("advisory Result facts differ from the projection")

    @staticmethod
    def _verify_run_closure(run: OnlySourceObservationV1, closure: Mapping[str, object]) -> None:
        row = run.canonical_payload.get("source_row")
        if not isinstance(row, Mapping):
            raise ValueError("advisory Run source row is unavailable")
        for field in (
            "run_id",
            "revision",
            "state",
            "specification_fingerprint",
            "research_result_fingerprint",
            "artifact_content_fingerprint",
            "calculation_execution_evidence_fingerprints",
        ):
            projection_name = {"revision": "run_revision", "state": "run_state"}.get(field, field)
            if row.get(field) != closure.get(projection_name):
                raise ValueError("advisory Run facts differ from the projection")
        provenance = row.get("authoring_provenance")
        authoring = provenance.get("execution_generation_fingerprint") if isinstance(provenance, Mapping) else None
        if authoring != closure.get("authoring_generation_fingerprint"):
            raise ValueError("advisory Run authoring generation differs from the projection")

    def _graph(self, result: OnlySourceObservationV1, graph_fingerprint: object) -> OnlyCalculationGraphDefinition:
        plan = result.canonical_payload.get("plan")
        calculations = plan.get("calculations") if isinstance(plan, Mapping) else None
        if not isinstance(graph_fingerprint, str) or not isinstance(calculations, list):
            raise ValueError("advisory Result calculation closure is incomplete")
        identities = {
            item.get("calculation_fingerprint")
            for item in calculations
            if isinstance(item, Mapping) and item.get("graph_fingerprint") == graph_fingerprint
        }
        if len(identities) != 1 or not isinstance(identity := next(iter(identities)), str):
            raise ValueError("advisory Result calculation closure is ambiguous")
        try:
            loaded = self._calculations.load_verified(identity)
            manifest = loaded.manifest
            graph = manifest.calculation_graph
        except Exception as exc:
            raise OnlyResearchAdvisoryUnavailableError("Calculation authority is unavailable") from exc
        if (
            not isinstance(graph, OnlyCalculationGraphDefinition)
            or manifest.calculation_fingerprint != identity
            or manifest.calculation_graph_fingerprint != graph_fingerprint
            or graph.fingerprint != graph_fingerprint
        ):
            raise ValueError("advisory Calculation Graph differs from the Result")
        return graph

    @staticmethod
    def _specification(run: OnlySourceObservationV1, identity: object) -> OnlyResearchSpecification:
        row = run.canonical_payload.get("source_row")
        if not isinstance(row, Mapping) or row.get("specification_fingerprint") != identity:
            raise ValueError("advisory Run Specification binding differs")
        raw = row.get("specification_payload")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(payload, Mapping):
                raise ValueError("Specification payload")
            specification = OnlyResearchSpecification.from_dict(payload)
        except Exception as exc:
            raise ValueError("advisory Run Specification is invalid") from exc
        if specification.specification_fingerprint != identity:
            raise ValueError("advisory Run Specification identity differs")
        return specification

    @staticmethod
    def _memory_ref(value: object) -> OnlyMemorySourceRefV1:
        if not isinstance(value, Mapping) or set(value) != {
            "source_family",
            "cut_fingerprint",
            "locator",
            "identity",
            "content_fingerprint",
        }:
            raise ValueError("advisory source reference is invalid")
        return OnlyMemorySourceRefV1(**cast(dict[str, str], value))

    @staticmethod
    def _one_record_ref(
        record: OnlyMemoryProjectionRecordV1, family: str, locator: object, identity: object
    ) -> OnlyMemorySourceRefV1:
        matches = tuple(
            ref
            for ref in record.source_refs
            if ref.source_family == family and ref.locator == locator and ref.identity == identity
        )
        if len(matches) != 1:
            raise ValueError("advisory owning Result relation is incomplete")
        return matches[0]

    @staticmethod
    def _observation(
        ref: OnlyMemorySourceRefV1,
        by_ref: Mapping[tuple[str, str, str, str, str], OnlySourceObservationV1],
    ) -> OnlySourceObservationV1:
        key = (ref.source_family, ref.cut_fingerprint, ref.locator, ref.identity, ref.content_fingerprint)
        try:
            return by_ref[key]
        except KeyError as exc:
            raise ValueError("advisory owning source fact is missing") from exc

    @staticmethod
    def _entry_ref(
        result: OnlyMemorySourceRefV1,
        run: OnlyMemorySourceRefV1,
        subject: OnlyExactEvaluationIntentSubjectV1,
    ) -> OnlyResearchAdvisorySourceRefV1:
        relation = {
            "result_source_ref": result.to_dict(),
            "run_source_ref": run.to_dict(),
            "subject_fingerprint": subject.subject_fingerprint,
        }
        return OnlyResearchAdvisorySourceRefV1(
            "EXPERIMENT_MEMORY_EVALUATION",
            only_canonical_json(relation),
            only_canonical_fingerprint({"domain": "onlyalpha.advisory-source", **relation}),
            only_canonical_fingerprint(
                {
                    "result_content_fingerprint": result.content_fingerprint,
                    "run_content_fingerprint": run.content_fingerprint,
                }
            ),
        )


def _jaccard(left: tuple[str, ...], right: tuple[str, ...]) -> Decimal:
    union = set(left) | set(right)
    return Decimal(1) if not union else Decimal(len(set(left) & set(right))) / Decimal(len(union))


def _numeric(value: OnlyResearchAdvisoryParameterV1) -> Decimal:
    raw = value.canonical_value.strip('"')
    return Decimal(raw)


def _parameter_similarity(
    left: tuple[OnlyResearchAdvisoryParameterV1, ...], right: tuple[OnlyResearchAdvisoryParameterV1, ...]
) -> Decimal:
    left_by_key, right_by_key = ({item.key: item for item in values} for values in (left, right))
    keys = set(left_by_key) | set(right_by_key)
    if not keys:
        return Decimal(1)
    total = Decimal(0)
    for key in keys:
        a, b = left_by_key.get(key), right_by_key.get(key)
        if a is None or b is None or a.value_kind != b.value_kind:
            continue
        if a.canonical_value == b.canonical_value:
            total += 1
        elif a.value_kind in {"DECIMAL", "INTEGER"}:
            av, bv = _numeric(a), _numeric(b)
            total += max(Decimal(0), Decimal(1) - abs(av - bv) / max(abs(av), abs(bv), Decimal(1)))
    return total / Decimal(len(keys))


def _score(current: OnlyResearchAdvisoryRepresentationV1, historical: OnlyResearchAdvisoryRepresentationV1) -> Decimal:
    value = (
        Decimal("0.30") * _jaccard(current.operator_features, historical.operator_features)
        + Decimal("0.20") * _jaccard(current.topology_features, historical.topology_features)
        + Decimal("0.25") * _parameter_similarity(current.parameter_features, historical.parameter_features)
        + Decimal("0.15") * _jaccard(current.output_features, historical.output_features)
        + Decimal("0.05") * Decimal(current.dataset_snapshot_fingerprint == historical.dataset_snapshot_fingerprint)
        + Decimal("0.05") * Decimal(current.evaluation_context_fingerprint == historical.evaluation_context_fingerprint)
    )
    return value.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN)


def _result(
    query: OnlyNearDuplicateQueryV1,
    index: OnlyResearchAdvisoryIndexV1,
    policy: OnlyNearDuplicateThresholdPolicyV1,
    status: OnlyNearDuplicateResultStatus,
    matches: tuple[OnlyNearDuplicateMatchV1, ...] = (),
    failure_code: str | None = None,
) -> OnlyNearDuplicateResultV1:
    return OnlyNearDuplicateResultV1(
        query.query_fingerprint,
        query.projection_revision,
        index.source_cut_fingerprint,
        REPRESENTATION_SCHEMA_VERSION,
        query.retrieval_algorithm_id,
        query.retrieval_algorithm_version,
        policy.policy_id,
        policy.policy_version,
        policy.policy_fingerprint,
        query.index_build_revision,
        status,
        matches,
        failure_code,
    )


def only_query_near_duplicates(
    *,
    current: OnlyResearchAdvisoryRepresentationV1,
    query: OnlyNearDuplicateQueryV1,
    index: OnlyResearchAdvisoryIndexV1 | None,
    policy: OnlyNearDuplicateThresholdPolicyV1,
    source_verifier: OnlyResearchAdvisorySourceVerifier,
) -> OnlyNearDuplicateResultV1:
    """Return advice only; this function has no Novelty or Research write capability."""
    if index is None:
        unavailable = OnlyResearchAdvisoryIndexV1(query.projection_revision, query.source_cut_fingerprint, ())
        return _result(
            query,
            unavailable,
            policy,
            OnlyNearDuplicateResultStatus.ADVISORY_UNAVAILABLE,
            failure_code="INDEX_UNAVAILABLE",
        )
    if (
        query.representation_fingerprint != current.representation_fingerprint
        or query.projection_revision != current.projection_revision
        or query.source_cut_fingerprint != current.source_cut_fingerprint
        or query.projection_revision != index.projection_revision
        or query.source_cut_fingerprint != index.source_cut_fingerprint
        or query.index_build_revision != index.index_build_revision
        or query.threshold_policy_fingerprint != policy.policy_fingerprint
        or query.requested_result_limit > policy.maximum_results
    ):
        return _result(
            query,
            index,
            policy,
            OnlyNearDuplicateResultStatus.ADVISORY_UNSUPPORTED,
            failure_code="QUERY_BINDING_UNSUPPORTED",
        )

    matches: list[OnlyNearDuplicateMatchV1] = []
    rejected = False
    for historical in index.representations:
        try:
            verified = source_verifier.load_representation_verified(
                historical.source_ref, index.projection_revision, historical.representation_schema_version
            )
        except OnlyResearchAdvisoryUnavailableError:
            return _result(
                query,
                index,
                policy,
                OnlyNearDuplicateResultStatus.ADVISORY_UNAVAILABLE,
                failure_code="SOURCE_AUTHORITY_UNAVAILABLE",
            )
        except Exception:
            rejected = True
            continue
        if verified != historical:
            rejected = True
            continue
        score = _score(current, historical)
        if score < policy.minimum_retrieval_score:
            continue
        comparisons = {
            "DATASET": current.dataset_snapshot_fingerprint == historical.dataset_snapshot_fingerprint,
            "EVALUATION_CONTEXT": current.evaluation_context_fingerprint == historical.evaluation_context_fingerprint,
            "OPERATORS": current.operator_features == historical.operator_features,
            "OUTPUT": current.output_features == historical.output_features,
            "PARAMETERS": current.parameter_features == historical.parameter_features,
            "TOPOLOGY": current.topology_features == historical.topology_features,
        }
        tiers = [OnlyNearDuplicateAdvisoryContextTier.RETRIEVABLE]
        if score >= policy.advisory_similarity_score:
            tiers.append(OnlyNearDuplicateAdvisoryContextTier.ADVISORY_SIMILAR)
        if comparisons["DATASET"] and comparisons["EVALUATION_CONTEXT"]:
            tiers.append(OnlyNearDuplicateAdvisoryContextTier.COMPARABLE)
        matches.append(
            OnlyNearDuplicateMatchV1(
                historical.source_ref.source_kind,
                historical.source_ref.native_locator,
                historical.source_ref.source_identity,
                historical.source_ref.source_revision,
                score,
                tuple(sorted(tiers, key=lambda item: item.value)),
                historical.representation_fingerprint,
                tuple(sorted(name for name, same in comparisons.items() if same)),
                tuple(sorted(name for name, same in comparisons.items() if not same)),
            )
        )
    ordered = tuple(
        sorted(matches, key=lambda item: (-item.score, item.source_kind, item.native_locator, item.source_identity))[
            : query.requested_result_limit
        ]
    )
    return _result(
        query,
        index,
        policy,
        OnlyNearDuplicateResultStatus.ADVISORY_PARTIAL if rejected else OnlyNearDuplicateResultStatus.ADVISORY_OK,
        ordered,
        "SOURCE_VERIFICATION_REJECTED" if rejected else None,
    )


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
