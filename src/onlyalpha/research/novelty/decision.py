"""Immutable Novelty Decision occurrence and decision-time proof witness."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.evaluation.subject import OnlyExactEvaluationIntentSubjectV1
from onlyalpha.research.memory.projector import (
    PROJECTION_SCHEMA_VERSION,
    PROJECTOR_ALGORITHM_VERSION,
    OnlyMemoryCutReader,
    OnlyMemorySourceRefV1,
    only_load_cut_observations,
)
from onlyalpha.research.memory.query import (
    QUERY_SCHEMA_VERSION,
    OnlyAgentFailureOwnerV1,
    OnlyExactEvaluationHistorySelectorV1,
    OnlyExactEvaluationIntentHistorySelectorV1,
    OnlyExactFailureEvidenceSelectorV1,
    OnlyExactFailureOwnerV1,
    OnlyExactStatisticsReferenceV1,
    OnlyMemoryHistoricalProofStatus,
    OnlyMemoryHistoricalQueryV1,
    OnlyQualificationFailureOwnerV1,
    OnlyResearchRunTerminalOwnerV1,
    OnlySearchFailureOwnerV1,
    only_query_experiment_memory_history,
)
from onlyalpha.research.memory.source_manifest import (
    OnlyExperimentMemorySourceCutManifestV1,
    OnlyMemoryProjectionError,
)
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.strategy.freeze_relation import OnlyStrategyFreezeRelation
from onlyalpha.strategy.qualification import (
    OnlyQualificationCriterionOutcome,
    OnlyQualificationDecision,
    OnlyQualificationEvidenceKind,
    OnlyQualificationOutcome,
)

from .model import (
    OnlyNoveltyPolicyCondition,
    OnlyNoveltyPolicyOutcome,
    OnlyNoveltyPolicyRevisionV1,
)
from .store import OnlyNoveltyPolicyStore

NOVELTY_DECISION_SCHEMA_VERSION = 1
NOVELTY_WITNESS_SCHEMA_VERSION = 1
NOVELTY_DECISION_REQUEST_SCHEMA_VERSION = 2
NOVELTY_DECISION_V2_SCHEMA_VERSION = 2
NOVELTY_WITNESS_V2_SCHEMA_VERSION = 2


class OnlyNoveltyDecisionError(RuntimeError):
    code = "NOVELTY_DECISION_INVALID"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class OnlyNoveltyDecisionConflictError(OnlyNoveltyDecisionError):
    code = "NOVELTY_DECISION_CONFLICT"


class OnlyNoveltyDecisionCorruptError(OnlyNoveltyDecisionError):
    code = "NOVELTY_DECISION_CORRUPT"


class OnlyNoveltyDecisionSchemaUnsupportedError(OnlyNoveltyDecisionError):
    code = "NOVELTY_DECISION_SCHEMA_UNSUPPORTED"


class OnlyNoveltyWitnessCorruptError(OnlyNoveltyDecisionError):
    code = "NOVELTY_WITNESS_CORRUPT"


class OnlyNoveltyWitnessSchemaUnsupportedError(OnlyNoveltyDecisionError):
    code = "NOVELTY_WITNESS_SCHEMA_UNSUPPORTED"


class OnlyHistoricalProofUnavailableError(OnlyNoveltyDecisionError):
    code = "HISTORICAL_PROOF_UNAVAILABLE"


class OnlyNoveltyDecisionSubjectType(StrEnum):
    EXACT_EVALUATION = "EXACT_EVALUATION"


class OnlyNoveltyProofRole(StrEnum):
    EVALUATION = "EVALUATION"
    QUALIFICATION_REJECT = "QUALIFICATION_REJECT"
    OPERATIONAL_FAILURE = "OPERATIONAL_FAILURE"
    SEARCH_OR_BUDGET_STOP = "SEARCH_OR_BUDGET_STOP"


class OnlyNoveltyDecisionReason(StrEnum):
    EXACT_EVALUATION_MATCH = "EXACT_EVALUATION_MATCH"
    CERTIFIED_EVALUATION_ABSENCE = "CERTIFIED_EVALUATION_ABSENCE"
    EXACT_NEGATIVE_EVIDENCE = "EXACT_NEGATIVE_EVIDENCE"
    HISTORICAL_PROOF_INCOMPLETE = "HISTORICAL_PROOF_INCOMPLETE"
    HISTORICAL_PROOF_UNAVAILABLE = "HISTORICAL_PROOF_UNAVAILABLE"
    OPERATIONAL_FAILURE_ONLY = "OPERATIONAL_FAILURE_ONLY"
    SEARCH_OR_BUDGET_STOP_ONLY = "SEARCH_OR_BUDGET_STOP_ONLY"


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise OnlyNoveltyDecisionError(f"{name} must be a lower-case SHA256")
    return value


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise OnlyNoveltyDecisionError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _command_id(value: object) -> str:
    if not isinstance(value, str):
        raise OnlyNoveltyDecisionError("Product Command ID is invalid")
    try:
        OnlyProductCommandId(value)
    except (TypeError, ValueError) as exc:
        raise OnlyNoveltyDecisionError("Product Command ID is invalid") from exc
    return value


@dataclass(frozen=True, slots=True)
class OnlyNoveltyQualificationBindingV1:
    decision_fingerprint: str
    policy_id: str
    policy_version: str
    policy_fingerprint: str

    def __post_init__(self) -> None:
        _sha(self.decision_fingerprint, "qualification decision fingerprint")
        _sha(self.policy_fingerprint, "qualification policy fingerprint")
        if (
            not isinstance(self.policy_id, str)
            or not self.policy_id
            or not isinstance(self.policy_version, str)
            or not self.policy_version
        ):
            raise OnlyNoveltyDecisionError("qualification policy identity is required")

    def to_dict(self) -> dict[str, str]:
        return {
            "decision_fingerprint": self.decision_fingerprint,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class OnlyNoveltyDecisionRequestV1:
    command_id: OnlyProductCommandId
    policy_id: str
    policy_version: str
    evaluation_selector: OnlyExactEvaluationHistorySelectorV1
    qualification_binding: OnlyNoveltyQualificationBindingV1 | None = None
    related_failures: tuple[OnlyExactFailureEvidenceSelectorV1, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, OnlyProductCommandId):
            raise OnlyNoveltyDecisionError("Product Command ID is invalid")
        if (
            not isinstance(self.policy_id, str)
            or not self.policy_id
            or not isinstance(self.policy_version, str)
            or not self.policy_version
        ):
            raise OnlyNoveltyDecisionError("exact Novelty Policy identity is required")
        if not isinstance(self.evaluation_selector, OnlyExactEvaluationHistorySelectorV1):
            raise OnlyNoveltyDecisionError("exact evaluation selector is required")
        if self.qualification_binding is not None and not isinstance(
            self.qualification_binding, OnlyNoveltyQualificationBindingV1
        ):
            raise OnlyNoveltyDecisionError("qualification binding is invalid")
        if any(
            not isinstance(item, OnlyExactFailureEvidenceSelectorV1)
            or item.classification not in {"OPERATIONAL_FAILURE", "SEARCH_OR_BUDGET_STOP"}
            for item in self.related_failures
        ):
            raise OnlyNoveltyDecisionError("related failures must use the operational/stop vocabulary")
        ordered = tuple(sorted(self.related_failures, key=lambda item: only_canonical_json(item.to_dict())))
        if (
            self.related_failures != ordered
            or len({only_canonical_json(item.to_dict()) for item in ordered}) != len(ordered)
            or len({item.classification for item in ordered}) != len(ordered)
        ):
            raise OnlyNoveltyDecisionError("related failures must be canonical and unique")

    def resolved_subject_dict(self) -> dict[str, object]:
        return {
            "subject_type": OnlyNoveltyDecisionSubjectType.EXACT_EVALUATION,
            "evaluation_selector": self.evaluation_selector.to_dict(),
            "qualification_binding": self.qualification_binding.to_dict() if self.qualification_binding else None,
            "related_failures": [item.to_dict() for item in self.related_failures],
        }

    @property
    def canonical_intent_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.research.novelty-decision-intent",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "resolved_subject": self.resolved_subject_dict(),
            }
        )


@dataclass(frozen=True, slots=True)
class OnlyNoveltyDecisionRequestV2:
    """Pre-run novelty request bound to a canonical Evaluation Intent Subject."""

    command_id: OnlyProductCommandId
    policy_id: str
    policy_version: str
    evaluation_subject: OnlyExactEvaluationIntentSubjectV1
    qualification_binding: OnlyNoveltyQualificationBindingV1 | None = None
    related_failures: tuple[OnlyExactFailureEvidenceSelectorV1, ...] = ()
    schema_version: int = NOVELTY_DECISION_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, OnlyProductCommandId):
            raise OnlyNoveltyDecisionError("Product Command ID is invalid")
        if (
            not isinstance(self.policy_id, str)
            or not self.policy_id
            or not isinstance(self.policy_version, str)
            or not self.policy_version
        ):
            raise OnlyNoveltyDecisionError("exact Novelty Policy identity is required")
        if not isinstance(self.evaluation_subject, OnlyExactEvaluationIntentSubjectV1):
            raise OnlyNoveltyDecisionError("exact Evaluation Intent Subject is required")
        if type(self.schema_version) is not int or self.schema_version != NOVELTY_DECISION_REQUEST_SCHEMA_VERSION:
            raise OnlyNoveltyDecisionSchemaUnsupportedError(str(self.schema_version))
        _validate_optional_novelty_bindings(self.qualification_binding, self.related_failures)

    def resolved_subject_dict(self) -> dict[str, object]:
        return {
            "subject_type": OnlyNoveltyDecisionSubjectType.EXACT_EVALUATION,
            "evaluation_subject": self.evaluation_subject.to_dict(),
            "qualification_binding": self.qualification_binding.to_dict() if self.qualification_binding else None,
            "related_failures": [item.to_dict() for item in self.related_failures],
        }

    @property
    def canonical_intent_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.research.novelty-decision-intent-v2",
                "request_schema_version": self.schema_version,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "resolved_subject": self.resolved_subject_dict(),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "command_id": self.command_id.value,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "evaluation_subject": self.evaluation_subject.to_dict(),
            "qualification_binding": self.qualification_binding.to_dict() if self.qualification_binding else None,
            "related_failures": [item.to_dict() for item in self.related_failures],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNoveltyDecisionRequestV2:
        expected = {
            "schema_version",
            "command_id",
            "policy_id",
            "policy_version",
            "evaluation_subject",
            "qualification_binding",
            "related_failures",
        }
        if set(payload) != expected:
            raise OnlyNoveltyDecisionError("Decision Request V2 fields are invalid")
        schema = payload["schema_version"]
        if type(schema) is not int or schema != NOVELTY_DECISION_REQUEST_SCHEMA_VERSION:
            raise OnlyNoveltyDecisionSchemaUnsupportedError(str(schema))
        if any(not isinstance(payload[name], str) or not payload[name] for name in ("policy_id", "policy_version")):
            raise OnlyNoveltyDecisionError("Decision Request V2 policy identity is invalid")
        subject, subject_binding, failures, _ = _parse_v2_resolved_subject(
            {
                "subject_type": OnlyNoveltyDecisionSubjectType.EXACT_EVALUATION,
                "evaluation_subject": payload["evaluation_subject"],
                "qualification_binding": payload["qualification_binding"],
                "related_failures": payload["related_failures"],
            }
        )
        result = cls(
            OnlyProductCommandId(_command_id(payload["command_id"])),
            cast(str, payload["policy_id"]),
            cast(str, payload["policy_version"]),
            subject,
            subject_binding,
            failures,
            schema,
        )
        if result.to_dict() != dict(payload):
            raise OnlyNoveltyDecisionError("Decision Request V2 is not canonical")
        return result


def _validate_optional_novelty_bindings(
    qualification_binding: OnlyNoveltyQualificationBindingV1 | None,
    related_failures: tuple[OnlyExactFailureEvidenceSelectorV1, ...],
) -> None:
    if qualification_binding is not None and not isinstance(qualification_binding, OnlyNoveltyQualificationBindingV1):
        raise OnlyNoveltyDecisionError("qualification binding is invalid")
    if any(
        not isinstance(item, OnlyExactFailureEvidenceSelectorV1)
        or item.classification not in {"OPERATIONAL_FAILURE", "SEARCH_OR_BUDGET_STOP"}
        for item in related_failures
    ):
        raise OnlyNoveltyDecisionError("related failures must use the operational/stop vocabulary")
    ordered = tuple(sorted(related_failures, key=lambda item: only_canonical_json(item.to_dict())))
    if (
        related_failures != ordered
        or len({only_canonical_json(item.to_dict()) for item in ordered}) != len(ordered)
        or len({item.classification for item in ordered}) != len(ordered)
    ):
        raise OnlyNoveltyDecisionError("related failures must be canonical and unique")


def _failure_selector_from_dict(payload: Mapping[str, object]) -> OnlyExactFailureEvidenceSelectorV1:
    if set(payload) != {"classification", "stable_code", "owner", "failure_phase"}:
        raise OnlyNoveltyDecisionError("related failure fields are invalid")
    raw_owner = _mapping(payload["owner"], "failure owner")
    owner_kind = raw_owner.get("owner_kind")
    try:
        if owner_kind == "RESEARCH_RUN":
            if set(raw_owner) != {
                "owner_kind",
                "run_id",
                "run_revision",
                "specification_fingerprint",
                "catalog_generation_fingerprint",
                "runtime_generation_fingerprint",
                "search_experiment_fingerprint",
                "search_iteration_plan_fingerprint",
                "terminal_state",
            }:
                raise ValueError("research run owner fields")
            owner: OnlyExactFailureOwnerV1 = OnlyResearchRunTerminalOwnerV1(
                cast(str, raw_owner["run_id"]),
                cast(int, raw_owner["run_revision"]),
                cast(str | None, raw_owner["specification_fingerprint"]),
                cast(str | None, raw_owner["catalog_generation_fingerprint"]),
                cast(str | None, raw_owner["runtime_generation_fingerprint"]),
                cast(str | None, raw_owner["search_experiment_fingerprint"]),
                cast(str | None, raw_owner["search_iteration_plan_fingerprint"]),
                cast(str, raw_owner["terminal_state"]),
            )
        elif owner_kind == "SEARCH_OCCURRENCE":
            if set(raw_owner) != {"owner_kind", "iteration_result_fingerprint"}:
                raise ValueError("search owner fields")
            owner = OnlySearchFailureOwnerV1(cast(str, raw_owner["iteration_result_fingerprint"]))
        elif owner_kind == "AGENT_OCCURRENCE":
            if set(raw_owner) != {"owner_kind", "occurrence_fingerprint"}:
                raise ValueError("agent owner fields")
            owner = OnlyAgentFailureOwnerV1(cast(str, raw_owner["occurrence_fingerprint"]))
        elif owner_kind == "QUALIFICATION_DECISION":
            if set(raw_owner) != {"owner_kind", "decision_fingerprint"}:
                raise ValueError("qualification owner fields")
            owner = OnlyQualificationFailureOwnerV1(cast(str, raw_owner["decision_fingerprint"]))
        else:
            raise ValueError("failure owner kind")
        classification = payload["classification"]
        stable_code = payload["stable_code"]
        failure_phase = payload["failure_phase"]
        if not isinstance(classification, str) or not classification:
            raise ValueError("failure classification")
        if stable_code is not None and (not isinstance(stable_code, str) or not stable_code):
            raise ValueError("failure stable code")
        if failure_phase is not None and (not isinstance(failure_phase, str) or not failure_phase):
            raise ValueError("failure phase")
        result = OnlyExactFailureEvidenceSelectorV1(classification, stable_code, owner, failure_phase)
    except (TypeError, ValueError) as exc:
        raise OnlyNoveltyDecisionError("related failure is invalid") from exc
    if result.to_dict() != dict(payload):
        raise OnlyNoveltyDecisionError("related failure is not canonical")
    return result


def _parse_v2_resolved_subject(
    payload: Mapping[str, object],
) -> tuple[
    OnlyExactEvaluationIntentSubjectV1,
    OnlyNoveltyQualificationBindingV1 | None,
    tuple[OnlyExactFailureEvidenceSelectorV1, ...],
    dict[str, object],
]:
    expected = {"subject_type", "evaluation_subject", "qualification_binding", "related_failures"}
    if set(payload) != expected or payload.get("subject_type") != OnlyNoveltyDecisionSubjectType.EXACT_EVALUATION:
        raise OnlyNoveltyDecisionError("Decision subject type is unsupported")
    evaluation_payload = _mapping(payload["evaluation_subject"], "evaluation subject")
    if type(evaluation_payload.get("schema_version")) is not int or evaluation_payload.get("schema_version") != 1:
        raise OnlyNoveltyDecisionError("evaluation subject schema is unsupported")
    try:
        evaluation_subject = OnlyExactEvaluationIntentHistorySelectorV1.from_dict(
            {"selector_schema_version": 1, "intent_subject": evaluation_payload}
        ).intent_subject
    except (TypeError, ValueError, RuntimeError) as exc:
        raise OnlyNoveltyDecisionError("evaluation subject is invalid") from exc
    raw_binding = payload["qualification_binding"]
    binding = None
    if raw_binding is not None:
        binding_payload = _mapping(raw_binding, "qualification binding")
        if set(binding_payload) != {"decision_fingerprint", "policy_id", "policy_version", "policy_fingerprint"}:
            raise OnlyNoveltyDecisionError("qualification binding fields are invalid")
        if any(
            not isinstance(binding_payload[name], str) or not binding_payload[name]
            for name in ("policy_id", "policy_version")
        ):
            raise OnlyNoveltyDecisionError("qualification binding policy identity is invalid")
        binding = OnlyNoveltyQualificationBindingV1(
            cast(str, binding_payload["decision_fingerprint"]),
            cast(str, binding_payload["policy_id"]),
            cast(str, binding_payload["policy_version"]),
            cast(str, binding_payload["policy_fingerprint"]),
        )
        if binding.to_dict() != dict(binding_payload):
            raise OnlyNoveltyDecisionError("qualification binding is not canonical")
    raw_failures = payload["related_failures"]
    if not isinstance(raw_failures, list):
        raise OnlyNoveltyDecisionError("related failures must be an array")
    failures = tuple(_failure_selector_from_dict(_mapping(item, "related failure")) for item in raw_failures)
    if [item.to_dict() for item in failures] != raw_failures:
        raise OnlyNoveltyDecisionError("related failures are not canonical")
    _validate_optional_novelty_bindings(binding, failures)
    normalized: dict[str, object] = {
        "subject_type": OnlyNoveltyDecisionSubjectType.EXACT_EVALUATION,
        "evaluation_subject": evaluation_subject.to_dict(),
        "qualification_binding": binding.to_dict() if binding else None,
        "related_failures": [item.to_dict() for item in failures],
    }
    if normalized != dict(payload):
        raise OnlyNoveltyDecisionError("Decision subject is not canonical")
    return evaluation_subject, binding, failures, normalized


@dataclass(frozen=True, slots=True, init=False)
class OnlyNoveltyDecisionSubjectV1:
    product_command_id: str
    canonical_intent_fingerprint: str
    _resolved_subject_json: str

    def __init__(
        self,
        product_command_id: str,
        canonical_intent_fingerprint: str,
        resolved_subject: Mapping[str, object],
    ) -> None:
        OnlyProductCommandId(product_command_id)
        _sha(canonical_intent_fingerprint, "canonical intent fingerprint")
        if resolved_subject.get("subject_type") != OnlyNoveltyDecisionSubjectType.EXACT_EVALUATION:
            raise OnlyNoveltyDecisionError("Decision subject type is unsupported")
        try:
            frozen = only_canonical_json(dict(resolved_subject))
        except (TypeError, ValueError, RuntimeError) as exc:
            raise OnlyNoveltyDecisionError("Decision subject is not canonicalizable") from exc
        object.__setattr__(self, "product_command_id", product_command_id)
        object.__setattr__(self, "canonical_intent_fingerprint", canonical_intent_fingerprint)
        object.__setattr__(self, "_resolved_subject_json", frozen)

    @property
    def resolved_subject(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], json.loads(self._resolved_subject_json))

    @property
    def subject_type(self) -> OnlyNoveltyDecisionSubjectType:
        return OnlyNoveltyDecisionSubjectType.EXACT_EVALUATION

    @property
    def subject_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.novelty-decision-subject", **dict(self.resolved_subject)}
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "product_command_id": self.product_command_id,
            "canonical_intent_fingerprint": self.canonical_intent_fingerprint,
            "resolved_subject": dict(self.resolved_subject),
            "subject_fingerprint": self.subject_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNoveltyDecisionSubjectV1:
        if set(payload) != {
            "product_command_id",
            "canonical_intent_fingerprint",
            "resolved_subject",
            "subject_fingerprint",
        }:
            raise OnlyNoveltyDecisionError("Decision subject fields are invalid")
        result = cls(
            str(payload["product_command_id"]),
            _sha(payload["canonical_intent_fingerprint"], "canonical intent fingerprint"),
            _mapping(payload["resolved_subject"], "resolved subject"),
        )
        if payload["subject_fingerprint"] != result.subject_fingerprint:
            raise OnlyNoveltyDecisionError("Decision subject fingerprint mismatch")
        return result


@dataclass(frozen=True, slots=True, init=False)
class OnlyNoveltyDecisionSubjectV2:
    product_command_id: str
    canonical_intent_fingerprint: str
    _resolved_subject_json: str

    def __init__(
        self,
        product_command_id: str,
        canonical_intent_fingerprint: str,
        resolved_subject: Mapping[str, object],
    ) -> None:
        try:
            OnlyProductCommandId(product_command_id)
            _sha(canonical_intent_fingerprint, "canonical intent fingerprint")
        except (TypeError, ValueError) as exc:
            raise OnlyNoveltyDecisionError("Decision subject identity is invalid") from exc
        try:
            _, _, _, normalized = _parse_v2_resolved_subject(resolved_subject)
            frozen = only_canonical_json(normalized)
        except (TypeError, ValueError, RuntimeError) as exc:
            raise OnlyNoveltyDecisionError("Decision subject is not canonicalizable") from exc
        object.__setattr__(self, "product_command_id", product_command_id)
        object.__setattr__(self, "canonical_intent_fingerprint", canonical_intent_fingerprint)
        object.__setattr__(self, "_resolved_subject_json", frozen)

    @property
    def resolved_subject(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], json.loads(self._resolved_subject_json))

    @property
    def subject_type(self) -> OnlyNoveltyDecisionSubjectType:
        return OnlyNoveltyDecisionSubjectType.EXACT_EVALUATION

    @property
    def subject_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.novelty-decision-subject-v2", **dict(self.resolved_subject)}
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "product_command_id": self.product_command_id,
            "canonical_intent_fingerprint": self.canonical_intent_fingerprint,
            "resolved_subject": dict(self.resolved_subject),
            "subject_fingerprint": self.subject_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNoveltyDecisionSubjectV2:
        if set(payload) != {
            "product_command_id",
            "canonical_intent_fingerprint",
            "resolved_subject",
            "subject_fingerprint",
        }:
            raise OnlyNoveltyDecisionError("Decision subject fields are invalid")
        result = cls(
            _command_id(payload["product_command_id"]),
            _sha(payload["canonical_intent_fingerprint"], "canonical intent fingerprint"),
            _mapping(payload["resolved_subject"], "resolved subject"),
        )
        if payload["subject_fingerprint"] != result.subject_fingerprint or result.to_dict() != dict(payload):
            raise OnlyNoveltyDecisionError("Decision subject fingerprint mismatch")
        return result


@dataclass(frozen=True, slots=True, init=False)
class OnlyNoveltyProofWitnessV1:
    role: OnlyNoveltyProofRole
    _query_json: str
    _proof_json: str

    def __init__(self, role: OnlyNoveltyProofRole, query: Mapping[str, object], proof: Mapping[str, object]) -> None:
        if not isinstance(role, OnlyNoveltyProofRole):
            raise OnlyNoveltyWitnessCorruptError("proof role is invalid")
        query = dict(query)
        proof = dict(proof)
        if set(query) != {
            "query_schema_version",
            "projection_revision_fingerprint",
            "query_kind",
            "exact_selector",
            "query_fingerprint",
        } or set(proof) != {
            "query_fingerprint",
            "projection_revision_fingerprint",
            "projection_logical_digest",
            "source_manifest_fingerprint",
            "proof_status",
            "ordered_matches",
            "failure_code",
            "result_fingerprint",
        }:
            raise OnlyNoveltyWitnessCorruptError("historical query/proof fields are invalid")
        if query.get("query_schema_version") != QUERY_SCHEMA_VERSION:
            raise OnlyNoveltyWitnessSchemaUnsupportedError(str(query.get("query_schema_version")))
        query_fingerprint = query.get("query_fingerprint")
        _sha(query_fingerprint, "query fingerprint")
        if (
            only_canonical_fingerprint({key: value for key, value in query.items() if key != "query_fingerprint"})
            != query_fingerprint
        ):
            raise OnlyNoveltyWitnessCorruptError("query fingerprint mismatch")
        result_fingerprint = proof.get("result_fingerprint")
        _sha(result_fingerprint, "historical proof result fingerprint")
        if (
            only_canonical_fingerprint({key: value for key, value in proof.items() if key != "result_fingerprint"})
            != result_fingerprint
        ):
            raise OnlyNoveltyWitnessCorruptError("historical proof fingerprint mismatch")
        if proof.get("query_fingerprint") != query_fingerprint or proof.get(
            "projection_revision_fingerprint"
        ) != query.get("projection_revision_fingerprint"):
            raise OnlyNoveltyWitnessCorruptError("query/proof binding mismatch")
        try:
            status = OnlyMemoryHistoricalProofStatus(str(proof.get("proof_status")))
        except ValueError as exc:
            raise OnlyNoveltyWitnessCorruptError("historical proof status is invalid") from exc
        expected_kind = "EVALUATION_EXACT" if role is OnlyNoveltyProofRole.EVALUATION else "FAILURE_EVIDENCE_EXACT"
        selector = query.get("exact_selector")
        if query.get("query_kind") != expected_kind or not isinstance(selector, Mapping):
            raise OnlyNoveltyWitnessCorruptError("proof role/query kind mismatch")
        expected_classification = {
            OnlyNoveltyProofRole.QUALIFICATION_REJECT: "QUALIFICATION_REJECT",
            OnlyNoveltyProofRole.OPERATIONAL_FAILURE: "OPERATIONAL_FAILURE",
            OnlyNoveltyProofRole.SEARCH_OR_BUDGET_STOP: "SEARCH_OR_BUDGET_STOP",
        }.get(role)
        if expected_classification is not None and selector.get("classification") != expected_classification:
            raise OnlyNoveltyWitnessCorruptError("proof role/classification mismatch")
        matches = proof.get("ordered_matches")
        if not isinstance(matches, list) or matches != sorted(matches, key=only_canonical_json):
            raise OnlyNoveltyWitnessCorruptError("historical matches are not canonical")
        if len({only_canonical_json(item) for item in matches}) != len(matches):
            raise OnlyNoveltyWitnessCorruptError("historical matches are duplicated")
        if (
            status in {OnlyMemoryHistoricalProofStatus.MATCH, OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH}
            and proof.get("failure_code") is not None
        ):
            raise OnlyNoveltyWitnessCorruptError("complete historical proof has a failure code")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "_query_json", only_canonical_json(query))
        object.__setattr__(self, "_proof_json", only_canonical_json(proof))

    @property
    def query(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], json.loads(self._query_json))

    @property
    def proof(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], json.loads(self._proof_json))

    @property
    def status(self) -> OnlyMemoryHistoricalProofStatus:
        return OnlyMemoryHistoricalProofStatus(str(self.proof["proof_status"]))

    @property
    def result_fingerprint(self) -> str:
        return cast(str, self.proof["result_fingerprint"])

    def to_dict(self) -> dict[str, object]:
        return {"role": self.role, "query": dict(self.query), "proof": dict(self.proof)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNoveltyProofWitnessV1:
        if set(payload) != {"role", "query", "proof"}:
            raise OnlyNoveltyWitnessCorruptError("proof witness fields are invalid")
        try:
            role = OnlyNoveltyProofRole(str(payload["role"]))
        except ValueError as exc:
            raise OnlyNoveltyWitnessCorruptError("proof role is invalid") from exc
        return cls(role, _mapping(payload["query"], "query"), _mapping(payload["proof"], "proof"))


@dataclass(frozen=True, slots=True, init=False)
class OnlyNoveltyProofWitnessV2:
    role: OnlyNoveltyProofRole
    _query_json: str
    _proof_json: str

    def __init__(self, role: OnlyNoveltyProofRole, query: Mapping[str, object], proof: Mapping[str, object]) -> None:
        if not isinstance(role, OnlyNoveltyProofRole):
            raise OnlyNoveltyWitnessCorruptError("proof role is invalid")
        query = dict(query)
        proof = dict(proof)
        if set(query) != {
            "query_schema_version",
            "projection_revision_fingerprint",
            "query_kind",
            "exact_selector",
            "query_fingerprint",
        } or set(proof) != {
            "query_fingerprint",
            "projection_revision_fingerprint",
            "projection_logical_digest",
            "source_manifest_fingerprint",
            "proof_status",
            "ordered_matches",
            "failure_code",
            "result_fingerprint",
        }:
            raise OnlyNoveltyWitnessCorruptError("historical query/proof fields are invalid")
        if query.get("query_schema_version") != QUERY_SCHEMA_VERSION:
            raise OnlyNoveltyWitnessSchemaUnsupportedError(str(query.get("query_schema_version")))
        query_fingerprint = query.get("query_fingerprint")
        _sha(query_fingerprint, "query fingerprint")
        if (
            only_canonical_fingerprint({key: value for key, value in query.items() if key != "query_fingerprint"})
            != query_fingerprint
        ):
            raise OnlyNoveltyWitnessCorruptError("query fingerprint mismatch")
        result_fingerprint = proof.get("result_fingerprint")
        _sha(result_fingerprint, "historical proof result fingerprint")
        if (
            only_canonical_fingerprint({key: value for key, value in proof.items() if key != "result_fingerprint"})
            != result_fingerprint
        ):
            raise OnlyNoveltyWitnessCorruptError("historical proof fingerprint mismatch")
        if proof.get("query_fingerprint") != query_fingerprint or proof.get(
            "projection_revision_fingerprint"
        ) != query.get("projection_revision_fingerprint"):
            raise OnlyNoveltyWitnessCorruptError("query/proof binding mismatch")
        try:
            status = OnlyMemoryHistoricalProofStatus(str(proof.get("proof_status")))
        except ValueError as exc:
            raise OnlyNoveltyWitnessCorruptError("historical proof status is invalid") from exc
        expected_kind = (
            "EVALUATION_INTENT_EXACT" if role is OnlyNoveltyProofRole.EVALUATION else "FAILURE_EVIDENCE_EXACT"
        )
        selector = query.get("exact_selector")
        if query.get("query_kind") != expected_kind or not isinstance(selector, Mapping):
            raise OnlyNoveltyWitnessCorruptError("proof role/query kind mismatch")
        if role is OnlyNoveltyProofRole.EVALUATION:
            try:
                parsed = OnlyExactEvaluationIntentHistorySelectorV1.from_dict(selector)
            except (TypeError, ValueError) as exc:
                raise OnlyNoveltyWitnessCorruptError("prospective evaluation selector is invalid") from exc
            if parsed.to_dict() != dict(selector):
                raise OnlyNoveltyWitnessCorruptError("prospective evaluation selector is not canonical")
        expected_classification = {
            OnlyNoveltyProofRole.QUALIFICATION_REJECT: "QUALIFICATION_REJECT",
            OnlyNoveltyProofRole.OPERATIONAL_FAILURE: "OPERATIONAL_FAILURE",
            OnlyNoveltyProofRole.SEARCH_OR_BUDGET_STOP: "SEARCH_OR_BUDGET_STOP",
        }.get(role)
        if expected_classification is not None and selector.get("classification") != expected_classification:
            raise OnlyNoveltyWitnessCorruptError("proof role/classification mismatch")
        matches = proof.get("ordered_matches")
        if not isinstance(matches, list) or matches != sorted(matches, key=only_canonical_json):
            raise OnlyNoveltyWitnessCorruptError("historical matches are not canonical")
        if len({only_canonical_json(item) for item in matches}) != len(matches):
            raise OnlyNoveltyWitnessCorruptError("historical matches are duplicated")
        if (
            status in {OnlyMemoryHistoricalProofStatus.MATCH, OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH}
            and proof.get("failure_code") is not None
        ):
            raise OnlyNoveltyWitnessCorruptError("complete historical proof has a failure code")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "_query_json", only_canonical_json(query))
        object.__setattr__(self, "_proof_json", only_canonical_json(proof))

    @property
    def query(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], json.loads(self._query_json))

    @property
    def proof(self) -> Mapping[str, object]:
        return cast(Mapping[str, object], json.loads(self._proof_json))

    @property
    def status(self) -> OnlyMemoryHistoricalProofStatus:
        return OnlyMemoryHistoricalProofStatus(str(self.proof["proof_status"]))

    @property
    def result_fingerprint(self) -> str:
        return cast(str, self.proof["result_fingerprint"])

    def to_dict(self) -> dict[str, object]:
        return {"role": self.role, "query": dict(self.query), "proof": dict(self.proof)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNoveltyProofWitnessV2:
        if set(payload) != {"role", "query", "proof"}:
            raise OnlyNoveltyWitnessCorruptError("proof witness fields are invalid")
        try:
            role = OnlyNoveltyProofRole(str(payload["role"]))
        except ValueError as exc:
            raise OnlyNoveltyWitnessCorruptError("proof role is invalid") from exc
        return cls(role, _mapping(payload["query"], "query"), _mapping(payload["proof"], "proof"))


@dataclass(frozen=True, slots=True)
class OnlyNoveltyNegativeEvidenceClosureV1:
    qualification_decision_fingerprint: str
    qualification_policy_id: str
    qualification_policy_version: str
    qualification_policy_fingerprint: str
    subject_strategy_fingerprint: str
    candidate_fingerprint: str
    research_result_locator: str
    research_result_fingerprint: str
    freeze_relation_fingerprint: str
    statistics_references: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        for name in (
            "qualification_decision_fingerprint",
            "qualification_policy_fingerprint",
            "subject_strategy_fingerprint",
            "candidate_fingerprint",
            "research_result_locator",
            "research_result_fingerprint",
            "freeze_relation_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if not self.qualification_policy_id or not self.qualification_policy_version:
            raise OnlyNoveltyWitnessCorruptError("qualification policy identity is incomplete")
        if not self.statistics_references or self.statistics_references != tuple(
            sorted(set(self.statistics_references))
        ):
            raise OnlyNoveltyWitnessCorruptError("statistics references must be canonical and non-empty")
        for logical, result in self.statistics_references:
            _sha(logical, "statistics fingerprint")
            _sha(result, "statistics result fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "qualification_decision_fingerprint": self.qualification_decision_fingerprint,
            "qualification_policy_id": self.qualification_policy_id,
            "qualification_policy_version": self.qualification_policy_version,
            "qualification_policy_fingerprint": self.qualification_policy_fingerprint,
            "subject_strategy_fingerprint": self.subject_strategy_fingerprint,
            "candidate_fingerprint": self.candidate_fingerprint,
            "research_result_locator": self.research_result_locator,
            "research_result_fingerprint": self.research_result_fingerprint,
            "freeze_relation_fingerprint": self.freeze_relation_fingerprint,
            "statistics_references": [list(item) for item in self.statistics_references],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNoveltyNegativeEvidenceClosureV1:
        expected = {
            "qualification_decision_fingerprint",
            "qualification_policy_id",
            "qualification_policy_version",
            "qualification_policy_fingerprint",
            "subject_strategy_fingerprint",
            "candidate_fingerprint",
            "research_result_locator",
            "research_result_fingerprint",
            "freeze_relation_fingerprint",
            "statistics_references",
        }
        if set(payload) != expected or not isinstance(payload["statistics_references"], list):
            raise OnlyNoveltyWitnessCorruptError("negative Evidence closure fields are invalid")
        try:
            references = tuple((str(item[0]), str(item[1])) for item in payload["statistics_references"])
        except (TypeError, IndexError) as exc:
            raise OnlyNoveltyWitnessCorruptError("statistics references are invalid") from exc
        return cls(
            str(payload["qualification_decision_fingerprint"]),
            str(payload["qualification_policy_id"]),
            str(payload["qualification_policy_version"]),
            str(payload["qualification_policy_fingerprint"]),
            str(payload["subject_strategy_fingerprint"]),
            str(payload["candidate_fingerprint"]),
            str(payload["research_result_locator"]),
            str(payload["research_result_fingerprint"]),
            str(payload["freeze_relation_fingerprint"]),
            references,
        )


@dataclass(frozen=True, slots=True)
class OnlyNoveltyDecisionWitnessV1:
    subject: OnlyNoveltyDecisionSubjectV1
    policy_id: str
    policy_version: str
    policy_fingerprint: str
    projection_schema_version: int
    projector_algorithm_version: int
    projection_revision_fingerprint: str
    projection_logical_digest: str
    source_manifest: OnlyExperimentMemorySourceCutManifestV1
    proofs: tuple[OnlyNoveltyProofWitnessV1, ...]
    negative_evidence: OnlyNoveltyNegativeEvidenceClosureV1 | None = None
    negative_evidence_failure_code: str | None = None
    schema_version: int = NOVELTY_WITNESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != NOVELTY_WITNESS_SCHEMA_VERSION:
            raise OnlyNoveltyWitnessSchemaUnsupportedError(str(self.schema_version))
        if (
            self.projection_schema_version != PROJECTION_SCHEMA_VERSION
            or self.projector_algorithm_version != PROJECTOR_ALGORITHM_VERSION
        ):
            raise OnlyNoveltyWitnessSchemaUnsupportedError("projection reader")
        for name in ("policy_fingerprint", "projection_revision_fingerprint", "projection_logical_digest"):
            _sha(getattr(self, name), name)
        if not self.policy_id or not self.policy_version or not self.proofs:
            raise OnlyNoveltyWitnessCorruptError("Witness bindings are incomplete")
        expected_intent = only_canonical_fingerprint(
            {
                "domain": "onlyalpha.research.novelty-decision-intent",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "resolved_subject": dict(self.subject.resolved_subject),
            }
        )
        if self.subject.canonical_intent_fingerprint != expected_intent:
            raise OnlyNoveltyWitnessCorruptError("Product intent does not bind the resolved subject and Policy")
        roles = tuple(item.role for item in self.proofs)
        if roles[0] is not OnlyNoveltyProofRole.EVALUATION or roles != tuple(
            sorted(roles, key=lambda item: item.value)
        ):
            raise OnlyNoveltyWitnessCorruptError("Witness proof roles are not canonical")
        if len(set(roles)) != len(roles):
            raise OnlyNoveltyWitnessCorruptError("Witness proof roles must be unique")
        resolved = self.subject.resolved_subject
        if set(resolved) != {
            "subject_type",
            "evaluation_selector",
            "qualification_binding",
            "related_failures",
        }:
            raise OnlyNoveltyWitnessCorruptError("Decision subject fields are invalid")
        expected_selectors = {
            OnlyNoveltyProofRole.EVALUATION: dict(_mapping(resolved.get("evaluation_selector"), "evaluation selector"))
        }
        qualification_binding = resolved.get("qualification_binding")
        if qualification_binding is not None:
            binding = _mapping(qualification_binding, "qualification binding")
            if set(binding) != {"decision_fingerprint", "policy_id", "policy_version", "policy_fingerprint"}:
                raise OnlyNoveltyWitnessCorruptError("qualification binding fields are invalid")
            expected_selectors[OnlyNoveltyProofRole.QUALIFICATION_REJECT] = {
                "classification": "QUALIFICATION_REJECT",
                "stable_code": "QUALIFICATION_REJECTED",
                "owner": {
                    "owner_kind": "QUALIFICATION_DECISION",
                    "decision_fingerprint": binding["decision_fingerprint"],
                },
                "failure_phase": None,
            }
        related_failures = resolved.get("related_failures")
        if not isinstance(related_failures, list):
            raise OnlyNoveltyWitnessCorruptError("related failures must be an array")
        for raw in related_failures:
            selector = dict(_mapping(raw, "related failure"))
            role = (
                OnlyNoveltyProofRole.SEARCH_OR_BUDGET_STOP
                if selector.get("classification") == "SEARCH_OR_BUDGET_STOP"
                else OnlyNoveltyProofRole.OPERATIONAL_FAILURE
            )
            if role in expected_selectors:
                raise OnlyNoveltyWitnessCorruptError("related failure roles must be unique")
            expected_selectors[role] = selector
        if set(roles) != set(expected_selectors) or any(
            item.query.get("exact_selector") != expected_selectors[item.role] for item in self.proofs
        ):
            raise OnlyNoveltyWitnessCorruptError("Witness proofs do not bind the exact Decision subject")
        if self.negative_evidence is not None and self.negative_evidence_failure_code is not None:
            raise OnlyNoveltyWitnessCorruptError("negative Evidence cannot be both complete and unavailable")
        if self.negative_evidence_failure_code not in {None, "HISTORICAL_PROOF_UNAVAILABLE"}:
            raise OnlyNoveltyWitnessCorruptError("negative Evidence failure code is invalid")
        qualification_proof = next(
            (item for item in self.proofs if item.role is OnlyNoveltyProofRole.QUALIFICATION_REJECT), None
        )
        if (self.negative_evidence is not None or self.negative_evidence_failure_code is not None) and (
            qualification_proof is None or qualification_proof.status is not OnlyMemoryHistoricalProofStatus.MATCH
        ):
            raise OnlyNoveltyWitnessCorruptError("negative Evidence requires an exact Qualification match")
        if self.negative_evidence is not None:
            evidence = self.negative_evidence
            selector = expected_selectors[OnlyNoveltyProofRole.EVALUATION]
            statistics = selector.get("statistics_references")
            expected_statistics = [
                {
                    "statistics_fingerprint": logical,
                    "statistics_result_fingerprint": result,
                }
                for logical, result in evidence.statistics_references
            ]
            if (
                evidence.candidate_fingerprint != selector.get("candidate_fingerprint")
                or evidence.research_result_locator != selector.get("result_plan_fingerprint")
                or statistics != expected_statistics
                or qualification_binding
                != {
                    "decision_fingerprint": evidence.qualification_decision_fingerprint,
                    "policy_id": evidence.qualification_policy_id,
                    "policy_version": evidence.qualification_policy_version,
                    "policy_fingerprint": evidence.qualification_policy_fingerprint,
                }
            ):
                raise OnlyNoveltyWitnessCorruptError("negative Evidence does not bind the exact Decision subject")
        for item in self.proofs:
            proof = item.proof
            if proof.get("projection_revision_fingerprint") != self.projection_revision_fingerprint:
                raise OnlyNoveltyWitnessCorruptError("proof Projection binding mismatch")
            if proof.get("projection_logical_digest") not in {None, self.projection_logical_digest}:
                raise OnlyNoveltyWitnessCorruptError("proof logical digest mismatch")
            if proof.get("source_manifest_fingerprint") not in {None, self.source_manifest.manifest_fingerprint}:
                raise OnlyNoveltyWitnessCorruptError("proof source manifest mismatch")

    @property
    def witness_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.novelty-decision-witness", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "subject": self.subject.to_dict(),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "projection_schema_version": self.projection_schema_version,
            "projector_algorithm_version": self.projector_algorithm_version,
            "projection_revision_fingerprint": self.projection_revision_fingerprint,
            "projection_logical_digest": self.projection_logical_digest,
            "source_manifest": self.source_manifest.to_dict(),
            "proofs": [item.to_dict() for item in self.proofs],
            "negative_evidence": self.negative_evidence.to_dict() if self.negative_evidence else None,
            "negative_evidence_failure_code": self.negative_evidence_failure_code,
        }
        if include_fingerprint:
            payload["witness_fingerprint"] = self.witness_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNoveltyDecisionWitnessV1:
        expected = {
            "schema_version",
            "subject",
            "policy_id",
            "policy_version",
            "policy_fingerprint",
            "projection_schema_version",
            "projector_algorithm_version",
            "projection_revision_fingerprint",
            "projection_logical_digest",
            "source_manifest",
            "proofs",
            "negative_evidence",
            "negative_evidence_failure_code",
            "witness_fingerprint",
        }
        if set(payload) != expected:
            raise OnlyNoveltyWitnessCorruptError("Witness fields are invalid")
        schema = payload["schema_version"]
        if type(schema) is not int or schema != NOVELTY_WITNESS_SCHEMA_VERSION:
            raise OnlyNoveltyWitnessSchemaUnsupportedError(str(schema))
        raw_proofs = payload["proofs"]
        if not isinstance(raw_proofs, list):
            raise OnlyNoveltyWitnessCorruptError("Witness proofs must be an array")
        negative = payload["negative_evidence"]
        result = cls(
            OnlyNoveltyDecisionSubjectV1.from_dict(_mapping(payload["subject"], "subject")),
            str(payload["policy_id"]),
            str(payload["policy_version"]),
            str(payload["policy_fingerprint"]),
            cast(int, payload["projection_schema_version"]),
            cast(int, payload["projector_algorithm_version"]),
            str(payload["projection_revision_fingerprint"]),
            str(payload["projection_logical_digest"]),
            OnlyExperimentMemorySourceCutManifestV1.from_dict(_mapping(payload["source_manifest"], "source manifest")),
            tuple(OnlyNoveltyProofWitnessV1.from_dict(_mapping(item, "proof witness")) for item in raw_proofs),
            None
            if negative is None
            else OnlyNoveltyNegativeEvidenceClosureV1.from_dict(_mapping(negative, "negative Evidence")),
            None
            if payload["negative_evidence_failure_code"] is None
            else str(payload["negative_evidence_failure_code"]),
            schema,
        )
        if payload["witness_fingerprint"] != result.witness_fingerprint:
            raise OnlyNoveltyWitnessCorruptError("Witness fingerprint mismatch")
        return result


@dataclass(frozen=True, slots=True)
class OnlyNoveltyDecisionWitnessV2:
    subject: OnlyNoveltyDecisionSubjectV2
    policy_id: str
    policy_version: str
    policy_fingerprint: str
    projection_schema_version: int
    projector_algorithm_version: int
    projection_revision_fingerprint: str
    projection_logical_digest: str
    source_manifest: OnlyExperimentMemorySourceCutManifestV1
    proofs: tuple[OnlyNoveltyProofWitnessV2, ...]
    negative_evidence: OnlyNoveltyNegativeEvidenceClosureV1 | None = None
    negative_evidence_failure_code: str | None = None
    schema_version: int = NOVELTY_WITNESS_V2_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != NOVELTY_WITNESS_V2_SCHEMA_VERSION:
            raise OnlyNoveltyWitnessSchemaUnsupportedError(str(self.schema_version))
        if (
            self.projection_schema_version != PROJECTION_SCHEMA_VERSION
            or self.projector_algorithm_version != PROJECTOR_ALGORITHM_VERSION
        ):
            raise OnlyNoveltyWitnessSchemaUnsupportedError("projection reader")
        for name in ("policy_fingerprint", "projection_revision_fingerprint", "projection_logical_digest"):
            _sha(getattr(self, name), name)
        if not self.policy_id or not self.policy_version or not self.proofs:
            raise OnlyNoveltyWitnessCorruptError("Witness bindings are incomplete")
        expected_intent = only_canonical_fingerprint(
            {
                "domain": "onlyalpha.research.novelty-decision-intent-v2",
                "request_schema_version": NOVELTY_DECISION_REQUEST_SCHEMA_VERSION,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "resolved_subject": dict(self.subject.resolved_subject),
            }
        )
        if self.subject.canonical_intent_fingerprint != expected_intent:
            raise OnlyNoveltyWitnessCorruptError("Product intent does not bind the resolved subject and Policy")
        roles = tuple(item.role for item in self.proofs)
        if roles[0] is not OnlyNoveltyProofRole.EVALUATION or roles != tuple(
            sorted(roles, key=lambda item: item.value)
        ):
            raise OnlyNoveltyWitnessCorruptError("Witness proof roles are not canonical")
        if len(set(roles)) != len(roles):
            raise OnlyNoveltyWitnessCorruptError("Witness proof roles must be unique")
        resolved = self.subject.resolved_subject
        if set(resolved) != {
            "subject_type",
            "evaluation_subject",
            "qualification_binding",
            "related_failures",
        }:
            raise OnlyNoveltyWitnessCorruptError("Decision subject fields are invalid")
        expected_selectors: dict[OnlyNoveltyProofRole, dict[str, object]] = {
            OnlyNoveltyProofRole.EVALUATION: {
                "selector_schema_version": 1,
                "intent_subject": dict(_mapping(resolved.get("evaluation_subject"), "evaluation subject")),
            }
        }
        qualification_binding = resolved.get("qualification_binding")
        if qualification_binding is not None:
            binding = _mapping(qualification_binding, "qualification binding")
            if set(binding) != {"decision_fingerprint", "policy_id", "policy_version", "policy_fingerprint"}:
                raise OnlyNoveltyWitnessCorruptError("qualification binding fields are invalid")
            expected_selectors[OnlyNoveltyProofRole.QUALIFICATION_REJECT] = {
                "classification": "QUALIFICATION_REJECT",
                "stable_code": "QUALIFICATION_REJECTED",
                "owner": {
                    "owner_kind": "QUALIFICATION_DECISION",
                    "decision_fingerprint": binding["decision_fingerprint"],
                },
                "failure_phase": None,
            }
        related_failures = resolved.get("related_failures")
        if not isinstance(related_failures, list):
            raise OnlyNoveltyWitnessCorruptError("related failures must be an array")
        for raw in related_failures:
            selector = dict(_mapping(raw, "related failure"))
            role = (
                OnlyNoveltyProofRole.SEARCH_OR_BUDGET_STOP
                if selector.get("classification") == "SEARCH_OR_BUDGET_STOP"
                else OnlyNoveltyProofRole.OPERATIONAL_FAILURE
            )
            if role in expected_selectors:
                raise OnlyNoveltyWitnessCorruptError("related failure roles must be unique")
            expected_selectors[role] = selector
        if set(roles) != set(expected_selectors) or any(
            item.query.get("exact_selector") != expected_selectors[item.role] for item in self.proofs
        ):
            raise OnlyNoveltyWitnessCorruptError("Witness proofs do not bind the exact Decision subject")
        if self.negative_evidence is not None and self.negative_evidence_failure_code is not None:
            raise OnlyNoveltyWitnessCorruptError("negative Evidence cannot be both complete and unavailable")
        if self.negative_evidence_failure_code not in {None, "HISTORICAL_PROOF_UNAVAILABLE"}:
            raise OnlyNoveltyWitnessCorruptError("negative Evidence failure code is invalid")
        qualification_proof = next(
            (item for item in self.proofs if item.role is OnlyNoveltyProofRole.QUALIFICATION_REJECT), None
        )
        if (self.negative_evidence is not None or self.negative_evidence_failure_code is not None) and (
            qualification_proof is None or qualification_proof.status is not OnlyMemoryHistoricalProofStatus.MATCH
        ):
            raise OnlyNoveltyWitnessCorruptError("negative Evidence requires an exact Qualification match")
        if self.negative_evidence is not None:
            evidence = self.negative_evidence
            subject = OnlyExactEvaluationIntentSubjectV1.from_dict(
                _mapping(resolved["evaluation_subject"], "evaluation subject")
            )
            if (
                evidence.candidate_fingerprint != subject.candidate_fingerprint
                or evidence.research_result_locator != subject.result_plan_fingerprint
                or tuple(logical for logical, _ in evidence.statistics_references) != subject.statistics_fingerprints
                or qualification_binding
                != {
                    "decision_fingerprint": evidence.qualification_decision_fingerprint,
                    "policy_id": evidence.qualification_policy_id,
                    "policy_version": evidence.qualification_policy_version,
                    "policy_fingerprint": evidence.qualification_policy_fingerprint,
                }
            ):
                raise OnlyNoveltyWitnessCorruptError("negative Evidence does not bind the exact Decision subject")
        for item in self.proofs:
            proof = item.proof
            if proof.get("projection_revision_fingerprint") != self.projection_revision_fingerprint:
                raise OnlyNoveltyWitnessCorruptError("proof Projection binding mismatch")
            if proof.get("projection_logical_digest") not in {None, self.projection_logical_digest}:
                raise OnlyNoveltyWitnessCorruptError("proof logical digest mismatch")
            if proof.get("source_manifest_fingerprint") not in {None, self.source_manifest.manifest_fingerprint}:
                raise OnlyNoveltyWitnessCorruptError("proof source manifest mismatch")

    @property
    def witness_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.novelty-decision-witness-v2", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "subject": self.subject.to_dict(),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "projection_schema_version": self.projection_schema_version,
            "projector_algorithm_version": self.projector_algorithm_version,
            "projection_revision_fingerprint": self.projection_revision_fingerprint,
            "projection_logical_digest": self.projection_logical_digest,
            "source_manifest": self.source_manifest.to_dict(),
            "proofs": [item.to_dict() for item in self.proofs],
            "negative_evidence": self.negative_evidence.to_dict() if self.negative_evidence else None,
            "negative_evidence_failure_code": self.negative_evidence_failure_code,
        }
        if include_fingerprint:
            payload["witness_fingerprint"] = self.witness_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNoveltyDecisionWitnessV2:
        expected = {
            "schema_version",
            "subject",
            "policy_id",
            "policy_version",
            "policy_fingerprint",
            "projection_schema_version",
            "projector_algorithm_version",
            "projection_revision_fingerprint",
            "projection_logical_digest",
            "source_manifest",
            "proofs",
            "negative_evidence",
            "negative_evidence_failure_code",
            "witness_fingerprint",
        }
        if set(payload) != expected:
            raise OnlyNoveltyWitnessCorruptError("Witness fields are invalid")
        schema = payload["schema_version"]
        if type(schema) is not int or schema != NOVELTY_WITNESS_V2_SCHEMA_VERSION:
            raise OnlyNoveltyWitnessSchemaUnsupportedError(str(schema))
        if any(not isinstance(payload[name], str) or not payload[name] for name in ("policy_id", "policy_version")):
            raise OnlyNoveltyWitnessCorruptError("Witness policy identity is invalid")
        if any(type(payload[name]) is not int for name in ("projection_schema_version", "projector_algorithm_version")):
            raise OnlyNoveltyWitnessCorruptError("Witness projection versions are invalid")
        raw_proofs = payload["proofs"]
        if not isinstance(raw_proofs, list):
            raise OnlyNoveltyWitnessCorruptError("Witness proofs must be an array")
        negative = payload["negative_evidence"]
        result = cls(
            OnlyNoveltyDecisionSubjectV2.from_dict(_mapping(payload["subject"], "subject")),
            str(payload["policy_id"]),
            str(payload["policy_version"]),
            str(payload["policy_fingerprint"]),
            cast(int, payload["projection_schema_version"]),
            cast(int, payload["projector_algorithm_version"]),
            str(payload["projection_revision_fingerprint"]),
            str(payload["projection_logical_digest"]),
            OnlyExperimentMemorySourceCutManifestV1.from_dict(_mapping(payload["source_manifest"], "source manifest")),
            tuple(OnlyNoveltyProofWitnessV2.from_dict(_mapping(item, "proof witness")) for item in raw_proofs),
            None
            if negative is None
            else OnlyNoveltyNegativeEvidenceClosureV1.from_dict(_mapping(negative, "negative Evidence")),
            None
            if payload["negative_evidence_failure_code"] is None
            else str(payload["negative_evidence_failure_code"]),
            schema,
        )
        if payload["witness_fingerprint"] != result.witness_fingerprint or result.to_dict() != dict(payload):
            raise OnlyNoveltyWitnessCorruptError("Witness fingerprint mismatch")
        return result


_REASONS = {
    OnlyNoveltyPolicyCondition.EXACT_COMPLETED_EVALUATION: OnlyNoveltyDecisionReason.EXACT_EVALUATION_MATCH,
    OnlyNoveltyPolicyCondition.CERTIFIED_NO_MATCH: OnlyNoveltyDecisionReason.CERTIFIED_EVALUATION_ABSENCE,
    OnlyNoveltyPolicyCondition.EXACT_COMPLETED_NEGATIVE_EVIDENCE: OnlyNoveltyDecisionReason.EXACT_NEGATIVE_EVIDENCE,
    OnlyNoveltyPolicyCondition.PROOF_INCOMPLETE: OnlyNoveltyDecisionReason.HISTORICAL_PROOF_INCOMPLETE,
    OnlyNoveltyPolicyCondition.PROOF_UNAVAILABLE: OnlyNoveltyDecisionReason.HISTORICAL_PROOF_UNAVAILABLE,
    OnlyNoveltyPolicyCondition.OPERATIONAL_FAILURE: OnlyNoveltyDecisionReason.OPERATIONAL_FAILURE_ONLY,
    OnlyNoveltyPolicyCondition.SEARCH_OR_BUDGET_STOP: OnlyNoveltyDecisionReason.SEARCH_OR_BUDGET_STOP_ONLY,
}


@dataclass(frozen=True, slots=True)
class OnlyNoveltyDecisionV1:
    subject: OnlyNoveltyDecisionSubjectV1
    policy_id: str
    policy_version: str
    policy_fingerprint: str
    witness_fingerprint: str
    derived_policy_condition: OnlyNoveltyPolicyCondition
    outcome: OnlyNoveltyPolicyOutcome
    reason_codes: tuple[OnlyNoveltyDecisionReason, ...]
    ordered_proof_references: tuple[str, ...]
    schema_version: int = NOVELTY_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != NOVELTY_DECISION_SCHEMA_VERSION:
            raise OnlyNoveltyDecisionSchemaUnsupportedError(str(self.schema_version))
        _sha(self.policy_fingerprint, "policy fingerprint")
        _sha(self.witness_fingerprint, "Witness fingerprint")
        if self.reason_codes != (_REASONS[self.derived_policy_condition],):
            raise OnlyNoveltyDecisionCorruptError("Decision reason does not match derived condition")
        if not self.ordered_proof_references or any(
            _sha(item, "proof reference") != item for item in self.ordered_proof_references
        ):
            raise OnlyNoveltyDecisionCorruptError("Decision proof references are invalid")

    @property
    def decision_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.novelty-decision", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "product_command_id": self.subject.product_command_id,
            "canonical_intent_fingerprint": self.subject.canonical_intent_fingerprint,
            "subject_type": self.subject.subject_type,
            "subject_fingerprint": self.subject.subject_fingerprint,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "witness_fingerprint": self.witness_fingerprint,
            "derived_policy_condition": self.derived_policy_condition,
            "outcome": self.outcome,
            "reason_codes": list(self.reason_codes),
            "ordered_proof_references": list(self.ordered_proof_references),
        }
        if include_fingerprint:
            payload["decision_fingerprint"] = self.decision_fingerprint
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
        subject: OnlyNoveltyDecisionSubjectV1,
    ) -> OnlyNoveltyDecisionV1:
        expected = {
            "schema_version",
            "product_command_id",
            "canonical_intent_fingerprint",
            "subject_type",
            "subject_fingerprint",
            "policy_id",
            "policy_version",
            "policy_fingerprint",
            "witness_fingerprint",
            "derived_policy_condition",
            "outcome",
            "reason_codes",
            "ordered_proof_references",
            "decision_fingerprint",
        }
        if set(payload) != expected:
            raise OnlyNoveltyDecisionCorruptError("Decision fields are invalid")
        schema = payload["schema_version"]
        if type(schema) is not int or schema != NOVELTY_DECISION_SCHEMA_VERSION:
            raise OnlyNoveltyDecisionSchemaUnsupportedError(str(schema))
        if (
            payload["product_command_id"] != subject.product_command_id
            or payload["canonical_intent_fingerprint"] != subject.canonical_intent_fingerprint
            or payload["subject_type"] != subject.subject_type
            or payload["subject_fingerprint"] != subject.subject_fingerprint
        ):
            raise OnlyNoveltyDecisionCorruptError("Decision subject binding mismatch")
        reasons = payload["reason_codes"]
        references = payload["ordered_proof_references"]
        if not isinstance(reasons, list) or not isinstance(references, list):
            raise OnlyNoveltyDecisionCorruptError("Decision reasons/proofs must be arrays")
        try:
            result = cls(
                subject,
                str(payload["policy_id"]),
                str(payload["policy_version"]),
                str(payload["policy_fingerprint"]),
                str(payload["witness_fingerprint"]),
                OnlyNoveltyPolicyCondition(str(payload["derived_policy_condition"])),
                OnlyNoveltyPolicyOutcome(str(payload["outcome"])),
                tuple(OnlyNoveltyDecisionReason(str(item)) for item in reasons),
                tuple(str(item) for item in references),
                schema,
            )
        except ValueError as exc:
            raise OnlyNoveltyDecisionCorruptError("Decision vocabulary is invalid") from exc
        if payload["decision_fingerprint"] != result.decision_fingerprint:
            raise OnlyNoveltyDecisionCorruptError("Decision fingerprint mismatch")
        return result


@dataclass(frozen=True, slots=True)
class OnlyNoveltyDecisionBundleV1:
    decision: OnlyNoveltyDecisionV1
    witness: OnlyNoveltyDecisionWitnessV1

    def __post_init__(self) -> None:
        if (
            self.decision.subject != self.witness.subject
            or self.decision.witness_fingerprint != self.witness.witness_fingerprint
        ):
            raise OnlyNoveltyDecisionCorruptError("Decision/Witness binding mismatch")
        if (
            self.decision.policy_id,
            self.decision.policy_version,
            self.decision.policy_fingerprint,
        ) != (self.witness.policy_id, self.witness.policy_version, self.witness.policy_fingerprint):
            raise OnlyNoveltyDecisionCorruptError("Decision/Witness Policy binding mismatch")
        if self.decision.ordered_proof_references != tuple(item.result_fingerprint for item in self.witness.proofs):
            raise OnlyNoveltyDecisionCorruptError("Decision proof references differ from Witness")

    def to_dict(self) -> dict[str, object]:
        return {"decision": self.decision.to_dict(), "witness": self.witness.to_dict()}


@dataclass(frozen=True, slots=True)
class OnlyNoveltyDecisionV2:
    subject: OnlyNoveltyDecisionSubjectV2
    policy_id: str
    policy_version: str
    policy_fingerprint: str
    witness_fingerprint: str
    derived_policy_condition: OnlyNoveltyPolicyCondition
    outcome: OnlyNoveltyPolicyOutcome
    reason_codes: tuple[OnlyNoveltyDecisionReason, ...]
    ordered_proof_references: tuple[str, ...]
    schema_version: int = NOVELTY_DECISION_V2_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != NOVELTY_DECISION_V2_SCHEMA_VERSION:
            raise OnlyNoveltyDecisionSchemaUnsupportedError(str(self.schema_version))
        _sha(self.policy_fingerprint, "policy fingerprint")
        _sha(self.witness_fingerprint, "Witness fingerprint")
        if self.reason_codes != (_REASONS[self.derived_policy_condition],):
            raise OnlyNoveltyDecisionCorruptError("Decision reason does not match derived condition")
        if not self.ordered_proof_references or any(
            _sha(item, "proof reference") != item for item in self.ordered_proof_references
        ):
            raise OnlyNoveltyDecisionCorruptError("Decision proof references are invalid")

    @property
    def decision_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.novelty-decision-v2", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "product_command_id": self.subject.product_command_id,
            "canonical_intent_fingerprint": self.subject.canonical_intent_fingerprint,
            "subject_type": self.subject.subject_type,
            "subject_fingerprint": self.subject.subject_fingerprint,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "witness_fingerprint": self.witness_fingerprint,
            "derived_policy_condition": self.derived_policy_condition,
            "outcome": self.outcome,
            "reason_codes": list(self.reason_codes),
            "ordered_proof_references": list(self.ordered_proof_references),
        }
        if include_fingerprint:
            payload["decision_fingerprint"] = self.decision_fingerprint
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
        subject: OnlyNoveltyDecisionSubjectV2,
    ) -> OnlyNoveltyDecisionV2:
        expected = {
            "schema_version",
            "product_command_id",
            "canonical_intent_fingerprint",
            "subject_type",
            "subject_fingerprint",
            "policy_id",
            "policy_version",
            "policy_fingerprint",
            "witness_fingerprint",
            "derived_policy_condition",
            "outcome",
            "reason_codes",
            "ordered_proof_references",
            "decision_fingerprint",
        }
        if set(payload) != expected:
            raise OnlyNoveltyDecisionCorruptError("Decision fields are invalid")
        schema = payload["schema_version"]
        if type(schema) is not int or schema != NOVELTY_DECISION_V2_SCHEMA_VERSION:
            raise OnlyNoveltyDecisionSchemaUnsupportedError(str(schema))
        if (
            payload["product_command_id"] != subject.product_command_id
            or payload["canonical_intent_fingerprint"] != subject.canonical_intent_fingerprint
            or payload["subject_type"] != subject.subject_type
            or payload["subject_fingerprint"] != subject.subject_fingerprint
        ):
            raise OnlyNoveltyDecisionCorruptError("Decision subject binding mismatch")
        reasons = payload["reason_codes"]
        references = payload["ordered_proof_references"]
        if (
            not isinstance(reasons, list)
            or not isinstance(references, list)
            or any(not isinstance(item, str) for item in reasons)
            or any(not isinstance(item, str) for item in references)
        ):
            raise OnlyNoveltyDecisionCorruptError("Decision reasons/proofs must be arrays")
        if any(not isinstance(payload[name], str) or not payload[name] for name in ("policy_id", "policy_version")):
            raise OnlyNoveltyDecisionCorruptError("Decision policy identity is invalid")
        try:
            result = cls(
                subject,
                str(payload["policy_id"]),
                str(payload["policy_version"]),
                str(payload["policy_fingerprint"]),
                str(payload["witness_fingerprint"]),
                OnlyNoveltyPolicyCondition(str(payload["derived_policy_condition"])),
                OnlyNoveltyPolicyOutcome(str(payload["outcome"])),
                tuple(OnlyNoveltyDecisionReason(str(item)) for item in reasons),
                tuple(str(item) for item in references),
                schema,
            )
        except ValueError as exc:
            raise OnlyNoveltyDecisionCorruptError("Decision vocabulary is invalid") from exc
        if payload["decision_fingerprint"] != result.decision_fingerprint or result.to_dict() != dict(payload):
            raise OnlyNoveltyDecisionCorruptError("Decision fingerprint mismatch")
        return result


@dataclass(frozen=True, slots=True)
class OnlyNoveltyDecisionBundleV2:
    decision: OnlyNoveltyDecisionV2
    witness: OnlyNoveltyDecisionWitnessV2

    def __post_init__(self) -> None:
        if (
            self.decision.subject != self.witness.subject
            or self.decision.witness_fingerprint != self.witness.witness_fingerprint
        ):
            raise OnlyNoveltyDecisionCorruptError("Decision/Witness binding mismatch")
        if (
            self.decision.policy_id,
            self.decision.policy_version,
            self.decision.policy_fingerprint,
        ) != (self.witness.policy_id, self.witness.policy_version, self.witness.policy_fingerprint):
            raise OnlyNoveltyDecisionCorruptError("Decision/Witness Policy binding mismatch")
        if self.decision.ordered_proof_references != tuple(item.result_fingerprint for item in self.witness.proofs):
            raise OnlyNoveltyDecisionCorruptError("Decision proof references differ from Witness")

    def to_dict(self) -> dict[str, object]:
        return {"decision": self.decision.to_dict(), "witness": self.witness.to_dict()}


class OnlyNoveltyQualificationDecisionReader(Protocol):
    def load_verified(self, decision_fingerprint: str) -> OnlyQualificationDecision: ...


class OnlyNoveltyFreezeRelationReader(Protocol):
    def load_freeze_relation(self, relation_fingerprint: str) -> OnlyStrategyFreezeRelation: ...


def _proof(
    role: OnlyNoveltyProofRole, revisions: OnlyExperimentMemoryRevisionStore, query: OnlyMemoryHistoricalQueryV1
) -> OnlyNoveltyProofWitnessV1:
    result = only_query_experiment_memory_history(revisions, query)
    return OnlyNoveltyProofWitnessV1(role, query.to_dict(), result.to_dict())


def _proof_v2(
    role: OnlyNoveltyProofRole, revisions: OnlyExperimentMemoryRevisionStore, query: OnlyMemoryHistoricalQueryV1
) -> OnlyNoveltyProofWitnessV2:
    result = only_query_experiment_memory_history(revisions, query)
    return OnlyNoveltyProofWitnessV2(role, query.to_dict(), result.to_dict())


def _negative_closure(
    request: OnlyNoveltyDecisionRequestV1,
    qualification_reader: OnlyNoveltyQualificationDecisionReader,
    freeze_reader: OnlyNoveltyFreezeRelationReader,
) -> OnlyNoveltyNegativeEvidenceClosureV1:
    binding = request.qualification_binding
    assert binding is not None
    try:
        decision = qualification_reader.load_verified(binding.decision_fingerprint)
        if (
            decision.decision_fingerprint != binding.decision_fingerprint
            or decision.outcome is not OnlyQualificationOutcome.REJECTED
            or (decision.policy_id, decision.policy_version, decision.policy_fingerprint)
            != (binding.policy_id, binding.policy_version, binding.policy_fingerprint)
            or not any(item.outcome is OnlyQualificationCriterionOutcome.FAIL for item in decision.criterion_results)
        ):
            raise ValueError("Qualification Decision binding is not an exact rejection")
        selector = request.evaluation_selector
        matches = tuple(
            evidence
            for evidence in decision.evidence
            if evidence.kind is OnlyQualificationEvidenceKind.RESEARCH_RESULT
            and evidence.locator_fingerprint == selector.result_plan_fingerprint
        )
        if len(matches) != 1 or matches[0].subject_binding_fingerprint is None:
            raise ValueError("Qualification Research Evidence relation is not unique")
        relation = freeze_reader.load_freeze_relation(matches[0].subject_binding_fingerprint)
        if (
            relation.relation_fingerprint != matches[0].subject_binding_fingerprint
            or relation.candidate_fingerprint != selector.candidate_fingerprint
            or relation.research_result_fingerprint != matches[0].evidence_fingerprint
            or relation.strategy_fingerprint != decision.subject_strategy_fingerprint
        ):
            raise ValueError("Qualification Freeze relation does not close the exact subject")
        statistics = tuple(
            (item.statistics_fingerprint, item.statistics_result_fingerprint) for item in selector.statistics_references
        )
        return OnlyNoveltyNegativeEvidenceClosureV1(
            decision.decision_fingerprint,
            decision.policy_id,
            decision.policy_version,
            decision.policy_fingerprint,
            decision.subject_strategy_fingerprint,
            selector.candidate_fingerprint,
            selector.result_plan_fingerprint,
            matches[0].evidence_fingerprint,
            relation.relation_fingerprint,
            statistics,
        )
    except Exception as exc:
        raise OnlyHistoricalProofUnavailableError("negative Evidence relation cannot be verified") from exc


def _negative_closure_v2(
    request: OnlyNoveltyDecisionRequestV2,
    evaluation_proof: OnlyNoveltyProofWitnessV2,
    qualification_reader: OnlyNoveltyQualificationDecisionReader,
    freeze_reader: OnlyNoveltyFreezeRelationReader,
) -> OnlyNoveltyNegativeEvidenceClosureV1:
    binding = request.qualification_binding
    assert binding is not None
    try:
        decision = qualification_reader.load_verified(binding.decision_fingerprint)
        if (
            decision.decision_fingerprint != binding.decision_fingerprint
            or decision.outcome is not OnlyQualificationOutcome.REJECTED
            or (decision.policy_id, decision.policy_version, decision.policy_fingerprint)
            != (binding.policy_id, binding.policy_version, binding.policy_fingerprint)
            or not any(item.outcome is OnlyQualificationCriterionOutcome.FAIL for item in decision.criterion_results)
        ):
            raise ValueError("Qualification Decision binding is not an exact rejection")
        matches = tuple(
            evidence
            for evidence in decision.evidence
            if evidence.kind is OnlyQualificationEvidenceKind.RESEARCH_RESULT
            and evidence.locator_fingerprint == request.evaluation_subject.result_plan_fingerprint
        )
        if len(matches) != 1 or matches[0].subject_binding_fingerprint is None:
            raise ValueError("Qualification Research Evidence relation is not unique")
        relation = freeze_reader.load_freeze_relation(matches[0].subject_binding_fingerprint)
        if (
            relation.relation_fingerprint != matches[0].subject_binding_fingerprint
            or relation.candidate_fingerprint != request.evaluation_subject.candidate_fingerprint
            or relation.research_result_fingerprint != matches[0].evidence_fingerprint
            or relation.strategy_fingerprint != decision.subject_strategy_fingerprint
        ):
            raise ValueError("Qualification Freeze relation does not close the exact subject")
        historical_matches = tuple(
            match
            for match in cast(list[object], evaluation_proof.proof["ordered_matches"])
            if isinstance(match, Mapping)
            and isinstance(match.get("facets"), Mapping)
            and match["facets"].get("research_result_fingerprint") == matches[0].evidence_fingerprint
        )
        if len(historical_matches) != 1:
            raise ValueError("Qualification Evidence does not identify one prospective evaluation match")
        facets = _mapping(historical_matches[0]["facets"], "evaluation match facets")
        raw_statistics = facets.get("statistics_references")
        if not isinstance(raw_statistics, list):
            raise ValueError("prospective evaluation statistics are unavailable")
        statistics = tuple(
            (
                reference.statistics_fingerprint,
                reference.statistics_result_fingerprint,
            )
            for reference in (
                OnlyExactStatisticsReferenceV1(
                    cast(str, _mapping(item, "statistics reference")["statistics_fingerprint"]),
                    cast(str, _mapping(item, "statistics reference")["statistics_result_fingerprint"]),
                )
                for item in raw_statistics
            )
        )
        return OnlyNoveltyNegativeEvidenceClosureV1(
            decision.decision_fingerprint,
            decision.policy_id,
            decision.policy_version,
            decision.policy_fingerprint,
            decision.subject_strategy_fingerprint,
            request.evaluation_subject.candidate_fingerprint,
            request.evaluation_subject.result_plan_fingerprint,
            matches[0].evidence_fingerprint,
            relation.relation_fingerprint,
            statistics,
        )
    except OnlyHistoricalProofUnavailableError:
        raise
    except Exception as exc:
        raise OnlyHistoricalProofUnavailableError("negative Evidence relation cannot be verified") from exc


def _condition(
    witness: OnlyNoveltyDecisionWitnessV1 | OnlyNoveltyDecisionWitnessV2,
) -> OnlyNoveltyPolicyCondition:
    statuses = tuple(item.status for item in witness.proofs)
    if (
        OnlyMemoryHistoricalProofStatus.PROOF_UNAVAILABLE in statuses
        or witness.negative_evidence_failure_code is not None
    ):
        return OnlyNoveltyPolicyCondition.PROOF_UNAVAILABLE
    if OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE in statuses:
        return OnlyNoveltyPolicyCondition.PROOF_INCOMPLETE
    evaluation = witness.proofs[0]
    if evaluation.status is not OnlyMemoryHistoricalProofStatus.MATCH and any(
        item.role is OnlyNoveltyProofRole.QUALIFICATION_REJECT and item.status is OnlyMemoryHistoricalProofStatus.MATCH
        for item in witness.proofs
    ):
        return OnlyNoveltyPolicyCondition.PROOF_INCOMPLETE
    if evaluation.status is OnlyMemoryHistoricalProofStatus.MATCH:
        return (
            OnlyNoveltyPolicyCondition.EXACT_COMPLETED_NEGATIVE_EVIDENCE
            if witness.negative_evidence is not None
            and any(
                item.role is OnlyNoveltyProofRole.QUALIFICATION_REJECT
                and item.status is OnlyMemoryHistoricalProofStatus.MATCH
                for item in witness.proofs
            )
            else OnlyNoveltyPolicyCondition.EXACT_COMPLETED_EVALUATION
        )
    if any(
        item.role is OnlyNoveltyProofRole.OPERATIONAL_FAILURE and item.status is OnlyMemoryHistoricalProofStatus.MATCH
        for item in witness.proofs
    ):
        return OnlyNoveltyPolicyCondition.OPERATIONAL_FAILURE
    if any(
        item.role is OnlyNoveltyProofRole.SEARCH_OR_BUDGET_STOP and item.status is OnlyMemoryHistoricalProofStatus.MATCH
        for item in witness.proofs
    ):
        return OnlyNoveltyPolicyCondition.SEARCH_OR_BUDGET_STOP
    return OnlyNoveltyPolicyCondition.CERTIFIED_NO_MATCH


def _evaluate(policy: OnlyNoveltyPolicyRevisionV1, witness: OnlyNoveltyDecisionWitnessV1) -> OnlyNoveltyDecisionV1:
    condition = _condition(witness)
    outcome = next(rule.outcome for rule in policy.rules if rule.condition is condition)
    return OnlyNoveltyDecisionV1(
        witness.subject,
        policy.policy_id,
        policy.policy_version,
        policy.policy_fingerprint,
        witness.witness_fingerprint,
        condition,
        outcome,
        (_REASONS[condition],),
        tuple(item.result_fingerprint for item in witness.proofs),
    )


def _evaluate_v2(policy: OnlyNoveltyPolicyRevisionV1, witness: OnlyNoveltyDecisionWitnessV2) -> OnlyNoveltyDecisionV2:
    condition = _condition(witness)
    outcome = next(rule.outcome for rule in policy.rules if rule.condition is condition)
    return OnlyNoveltyDecisionV2(
        witness.subject,
        policy.policy_id,
        policy.policy_version,
        policy.policy_fingerprint,
        witness.witness_fingerprint,
        condition,
        outcome,
        (_REASONS[condition],),
        tuple(item.result_fingerprint for item in witness.proofs),
    )


def _build_novelty_decision_bundle(
    request: OnlyNoveltyDecisionRequestV1,
    projection_revision_fingerprint: str,
    revisions: OnlyExperimentMemoryRevisionStore,
    policies: OnlyNoveltyPolicyStore,
    *,
    qualification_decisions: OnlyNoveltyQualificationDecisionReader | None = None,
    freeze_relations: OnlyNoveltyFreezeRelationReader | None = None,
) -> OnlyNoveltyDecisionBundleV1:
    """Build authority-verified content from exact readers."""
    policy = policies.load_exact(request.policy_id, request.policy_version)
    projection = revisions.load_verified(projection_revision_fingerprint)
    subject = OnlyNoveltyDecisionSubjectV1(
        request.command_id.value, request.canonical_intent_fingerprint, request.resolved_subject_dict()
    )
    proofs = [
        _proof(
            OnlyNoveltyProofRole.EVALUATION,
            revisions,
            OnlyMemoryHistoricalQueryV1(projection.revision_fingerprint, request.evaluation_selector),
        )
    ]
    negative = None
    negative_failure = None
    if request.qualification_binding is not None:
        qualification_query = OnlyMemoryHistoricalQueryV1(
            projection.revision_fingerprint,
            OnlyExactFailureEvidenceSelectorV1(
                "QUALIFICATION_REJECT",
                "QUALIFICATION_REJECTED",
                OnlyQualificationFailureOwnerV1(request.qualification_binding.decision_fingerprint),
            ),
        )
        qualification_proof = _proof(OnlyNoveltyProofRole.QUALIFICATION_REJECT, revisions, qualification_query)
        proofs.append(qualification_proof)
        if qualification_proof.status is OnlyMemoryHistoricalProofStatus.MATCH:
            if qualification_decisions is None or freeze_relations is None:
                negative_failure = "HISTORICAL_PROOF_UNAVAILABLE"
            else:
                try:
                    negative = _negative_closure(request, qualification_decisions, freeze_relations)
                except OnlyHistoricalProofUnavailableError:
                    negative_failure = "HISTORICAL_PROOF_UNAVAILABLE"
    for selector in request.related_failures:
        role = (
            OnlyNoveltyProofRole.SEARCH_OR_BUDGET_STOP
            if selector.classification == "SEARCH_OR_BUDGET_STOP"
            else OnlyNoveltyProofRole.OPERATIONAL_FAILURE
        )
        proofs.append(_proof(role, revisions, OnlyMemoryHistoricalQueryV1(projection.revision_fingerprint, selector)))
    proofs.sort(key=lambda item: item.role.value)
    witness = OnlyNoveltyDecisionWitnessV1(
        subject,
        policy.policy_id,
        policy.policy_version,
        policy.policy_fingerprint,
        PROJECTION_SCHEMA_VERSION,
        PROJECTOR_ALGORITHM_VERSION,
        projection.revision_fingerprint,
        projection.logical_digest,
        projection.source_manifest,
        tuple(proofs),
        negative,
        negative_failure,
    )
    return OnlyNoveltyDecisionBundleV1(_evaluate(policy, witness), witness)


def _build_novelty_decision_bundle_v2(
    request: OnlyNoveltyDecisionRequestV2,
    projection_revision_fingerprint: str,
    revisions: OnlyExperimentMemoryRevisionStore,
    policies: OnlyNoveltyPolicyStore,
    *,
    qualification_decisions: OnlyNoveltyQualificationDecisionReader | None = None,
    freeze_relations: OnlyNoveltyFreezeRelationReader | None = None,
) -> OnlyNoveltyDecisionBundleV2:
    """Build a pre-run Decision from the canonical intent subject."""
    policy = policies.load_exact(request.policy_id, request.policy_version)
    projection = revisions.load_verified(projection_revision_fingerprint)
    subject = OnlyNoveltyDecisionSubjectV2(
        request.command_id.value, request.canonical_intent_fingerprint, request.resolved_subject_dict()
    )
    evaluation_query = OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint,
        OnlyExactEvaluationIntentHistorySelectorV1(request.evaluation_subject),
    )
    evaluation_proof = _proof_v2(OnlyNoveltyProofRole.EVALUATION, revisions, evaluation_query)
    proofs = [evaluation_proof]
    negative = None
    negative_failure = None
    if request.qualification_binding is not None:
        qualification_query = OnlyMemoryHistoricalQueryV1(
            projection.revision_fingerprint,
            OnlyExactFailureEvidenceSelectorV1(
                "QUALIFICATION_REJECT",
                "QUALIFICATION_REJECTED",
                OnlyQualificationFailureOwnerV1(request.qualification_binding.decision_fingerprint),
            ),
        )
        qualification_proof = _proof_v2(OnlyNoveltyProofRole.QUALIFICATION_REJECT, revisions, qualification_query)
        proofs.append(qualification_proof)
        if qualification_proof.status is OnlyMemoryHistoricalProofStatus.MATCH:
            if qualification_decisions is None or freeze_relations is None:
                negative_failure = "HISTORICAL_PROOF_UNAVAILABLE"
            else:
                try:
                    negative = _negative_closure_v2(
                        request, evaluation_proof, qualification_decisions, freeze_relations
                    )
                except OnlyHistoricalProofUnavailableError:
                    negative_failure = "HISTORICAL_PROOF_UNAVAILABLE"
    for selector in request.related_failures:
        role = (
            OnlyNoveltyProofRole.SEARCH_OR_BUDGET_STOP
            if selector.classification == "SEARCH_OR_BUDGET_STOP"
            else OnlyNoveltyProofRole.OPERATIONAL_FAILURE
        )
        proofs.append(
            _proof_v2(role, revisions, OnlyMemoryHistoricalQueryV1(projection.revision_fingerprint, selector))
        )
    proofs.sort(key=lambda item: item.role.value)
    witness = OnlyNoveltyDecisionWitnessV2(
        subject,
        policy.policy_id,
        policy.policy_version,
        policy.policy_fingerprint,
        PROJECTION_SCHEMA_VERSION,
        PROJECTOR_ALGORITHM_VERSION,
        projection.revision_fingerprint,
        projection.logical_digest,
        projection.source_manifest,
        tuple(proofs),
        negative,
        negative_failure,
    )
    return OnlyNoveltyDecisionBundleV2(_evaluate_v2(policy, witness), witness)


def only_verify_historical_novelty_decision(
    bundle: OnlyNoveltyDecisionBundleV1 | OnlyNoveltyDecisionBundleV2,
    policies: OnlyNoveltyPolicyStore,
    source_readers: Mapping[str, OnlyMemoryCutReader],
    *,
    qualification_decisions: OnlyNoveltyQualificationDecisionReader | None = None,
    freeze_relations: OnlyNoveltyFreezeRelationReader | None = None,
) -> OnlyNoveltyDecisionV1 | OnlyNoveltyDecisionV2:
    """Replay the frozen Witness without querying active/current Experiment Memory."""
    try:
        policy = policies.load_exact(bundle.decision.policy_id, bundle.decision.policy_version)
        if policy.policy_fingerprint != bundle.decision.policy_fingerprint:
            raise OnlyNoveltyDecisionCorruptError("historical Policy fingerprint mismatch")
        observations = only_load_cut_observations(bundle.witness.source_manifest, source_readers)
        available = {
            (item.source_family, item.cut_fingerprint, item.locator, item.identity, item.content_fingerprint)
            for item in observations
        }
        for proof in bundle.witness.proofs:
            matches = cast(Sequence[Mapping[str, object]], proof.proof["ordered_matches"])
            for match in matches:
                refs = match.get("source_refs")
                if not isinstance(refs, list):
                    raise OnlyNoveltyWitnessCorruptError("historical source references are invalid")
                for raw in refs:
                    value = _mapping(raw, "source reference")
                    ref = OnlyMemorySourceRefV1(
                        str(value.get("source_family")),
                        str(value.get("cut_fingerprint")),
                        str(value.get("locator")),
                        str(value.get("identity")),
                        str(value.get("content_fingerprint")),
                    )
                    if (
                        ref.source_family,
                        ref.cut_fingerprint,
                        ref.locator,
                        ref.identity,
                        ref.content_fingerprint,
                    ) not in available:
                        raise OnlyHistoricalProofUnavailableError("historical source fact is unavailable")
        negative = bundle.witness.negative_evidence
        if negative is not None:
            if qualification_decisions is None or freeze_relations is None:
                raise OnlyHistoricalProofUnavailableError("negative Evidence readers are unavailable")
            binding = OnlyNoveltyQualificationBindingV1(
                negative.qualification_decision_fingerprint,
                negative.qualification_policy_id,
                negative.qualification_policy_version,
                negative.qualification_policy_fingerprint,
            )
            resolved = bundle.witness.subject.resolved_subject
            selector = _mapping(
                resolved.get(
                    "evaluation_selector"
                    if isinstance(bundle.witness, OnlyNoveltyDecisionWitnessV1)
                    else "evaluation_subject"
                ),
                "evaluation selector",
            )
            evaluation_proof = next(
                item for item in bundle.witness.proofs if item.role is OnlyNoveltyProofRole.EVALUATION
            )
            evaluation_matches = tuple(
                match
                for match in cast(list[object], evaluation_proof.proof["ordered_matches"])
                if isinstance(match, Mapping)
                and isinstance(match.get("facets"), Mapping)
                and match["facets"].get("research_result_fingerprint") == negative.research_result_fingerprint
            )
            if len(evaluation_matches) != 1:
                raise OnlyHistoricalProofUnavailableError("historical negative Evidence evaluation is not unique")
            evaluation_facets = _mapping(evaluation_matches[0]["facets"], "evaluation match facets")
            if evaluation_facets.get("research_result_locator") != negative.research_result_locator:
                raise OnlyHistoricalProofUnavailableError("historical negative Evidence result locator differs")
            raw_statistics = evaluation_facets.get("statistics_references")
            if not isinstance(raw_statistics, list):
                raise OnlyHistoricalProofUnavailableError("historical negative Evidence statistics are unavailable")
            try:
                statistics = tuple(
                    (
                        reference.statistics_fingerprint,
                        reference.statistics_result_fingerprint,
                    )
                    for reference in (
                        OnlyExactStatisticsReferenceV1(
                            cast(str, _mapping(item, "statistics reference")["statistics_fingerprint"]),
                            cast(str, _mapping(item, "statistics reference")["statistics_result_fingerprint"]),
                        )
                        for item in raw_statistics
                    )
                )
            except (TypeError, ValueError, KeyError) as exc:
                raise OnlyHistoricalProofUnavailableError(
                    "historical negative Evidence statistics are invalid"
                ) from exc
            if statistics != negative.statistics_references:
                raise OnlyHistoricalProofUnavailableError("historical negative Evidence statistics differ")
            decision = qualification_decisions.load_verified(binding.decision_fingerprint)
            relation = freeze_relations.load_freeze_relation(negative.freeze_relation_fingerprint)
            if (
                decision.decision_fingerprint != binding.decision_fingerprint
                or decision.outcome is not OnlyQualificationOutcome.REJECTED
                or (decision.policy_id, decision.policy_version, decision.policy_fingerprint)
                != (binding.policy_id, binding.policy_version, binding.policy_fingerprint)
                or not any(
                    item.outcome is OnlyQualificationCriterionOutcome.FAIL for item in decision.criterion_results
                )
                or relation.relation_fingerprint != negative.freeze_relation_fingerprint
                or relation.candidate_fingerprint != negative.candidate_fingerprint
                or negative.candidate_fingerprint != selector.get("candidate_fingerprint")
                or negative.research_result_locator != selector.get("result_plan_fingerprint")
                or relation.research_result_fingerprint != negative.research_result_fingerprint
                or relation.strategy_fingerprint != negative.subject_strategy_fingerprint
            ):
                raise OnlyHistoricalProofUnavailableError("historical negative Evidence relation differs")
            qualification_matches = tuple(
                evidence
                for evidence in decision.evidence
                if evidence.kind is OnlyQualificationEvidenceKind.RESEARCH_RESULT
                and evidence.locator_fingerprint == negative.research_result_locator
                and evidence.evidence_fingerprint == negative.research_result_fingerprint
                and evidence.subject_binding_fingerprint == negative.freeze_relation_fingerprint
            )
            if len(qualification_matches) != 1:
                raise OnlyHistoricalProofUnavailableError("historical Qualification Evidence relation differs")
        expected = (
            _evaluate_v2(policy, bundle.witness)
            if isinstance(bundle.witness, OnlyNoveltyDecisionWitnessV2)
            else _evaluate(policy, bundle.witness)
        )
        if expected != bundle.decision or expected.decision_fingerprint != bundle.decision.decision_fingerprint:
            raise OnlyNoveltyDecisionCorruptError("historical Decision replay mismatch")
        return expected
    except (OnlyNoveltyDecisionError, OnlyMemoryProjectionError):
        raise
    except Exception as exc:
        raise OnlyHistoricalProofUnavailableError("historical proof cannot be verified") from exc


__all__ = [name for name in globals() if name.startswith(("NOVELTY_", "OnlyNovelty", "OnlyHistorical", "only_"))]
