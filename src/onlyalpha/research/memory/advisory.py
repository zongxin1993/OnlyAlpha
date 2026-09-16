"""Versioned, disposable near-duplicate advice over verified Research facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Protocol, cast

from onlyalpha.calculation.definition import OnlyCalculationDefinition, OnlyCalculationScalar
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.evaluation.subject import OnlyExactEvaluationIntentSubjectV1
from onlyalpha.research.specification.model import OnlyResearchSpecification

REPRESENTATION_SCHEMA_VERSION = 1
QUERY_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1
STRUCTURED_ALGORITHM_ID = "STRUCTURED_NEAR_DUPLICATE"
STRUCTURED_ALGORITHM_VERSION = "1"


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
        if self.representation_schema_version != REPRESENTATION_SCHEMA_VERSION:
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
        fingerprint = payload.get("representation_fingerprint")
        fields = dict(payload)
        fields.pop("representation_fingerprint", None)
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
        }
        if set(fields) != expected:
            raise ValueError("advisory representation fields are invalid")
        for name in ("source_ref",):
            if not isinstance(fields[name], Mapping):
                raise ValueError(f"{name} must be an object")
        for name in ("operator_features", "topology_features", "parameter_features", "output_features"):
            if not isinstance(fields[name], list):
                raise ValueError(f"{name} must be an array")
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
        if fingerprint is not None and fingerprint != result.representation_fingerprint:
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
        if self.index_schema_version != INDEX_SCHEMA_VERSION:
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
            self.schema_version != 1
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
            self.query_schema_version != QUERY_SCHEMA_VERSION
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


class OnlyNearDuplicateContextTier(StrEnum):
    RETRIEVABLE = "RETRIEVABLE"
    COMPARABLE = "COMPARABLE"
    ADVISORY_SIMILAR = "ADVISORY_SIMILAR"
    HARD_REUSE_ELIGIBLE = "HARD_REUSE_ELIGIBLE"
    HARD_SUPPRESSION_ELIGIBLE = "HARD_SUPPRESSION_ELIGIBLE"


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
    context_tiers: tuple[OnlyNearDuplicateContextTier, ...]
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
            or self.context_tiers != tuple(sorted(set(self.context_tiers), key=lambda item: item.value))
            or self.same != tuple(sorted(set(self.same)))
            or self.different != tuple(sorted(set(self.different)))
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
            self.result_schema_version != RESULT_SCHEMA_VERSION
            or self.representation_schema_version != REPRESENTATION_SCHEMA_VERSION
        ):
            raise ValueError("near-duplicate result schema is unsupported")
        if self.status is OnlyNearDuplicateResultStatus.ADVISORY_OK and self.failure_code is not None:
            raise ValueError("successful advisory result cannot carry a failure code")
        if self.status is not OnlyNearDuplicateResultStatus.ADVISORY_OK and not self.failure_code:
            raise ValueError("non-success advisory result requires a failure code")
        if self.matches != tuple(
            sorted(
                self.matches,
                key=lambda item: (-item.score, item.source_kind, item.native_locator, item.source_identity),
            )
        ):
            raise ValueError("near-duplicate matches are not deterministically ordered")
        if any(value is not None for value in (self.model_id, self.model_version, self.model_content_fingerprint)):
            raise ValueError("STRUCTURED_NEAR_DUPLICATE_V1 does not accept model identity")

    def to_dict(self) -> dict[str, object]:
        return {
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


class OnlyResearchAdvisorySourceVerifier(Protocol):
    def load_representation_verified(
        self,
        source_ref: OnlyResearchAdvisorySourceRefV1,
        projection_revision: str,
        representation_schema_version: int,
    ) -> OnlyResearchAdvisoryRepresentationV1: ...


class OnlyResearchAdvisoryUnavailableError(RuntimeError):
    pass


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
        tiers = [OnlyNearDuplicateContextTier.RETRIEVABLE]
        if score >= policy.advisory_similarity_score:
            tiers.append(OnlyNearDuplicateContextTier.ADVISORY_SIMILAR)
        if comparisons["DATASET"] and comparisons["EVALUATION_CONTEXT"]:
            tiers.append(OnlyNearDuplicateContextTier.COMPARABLE)
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
