"""Immutable evidence-backed Strategy Qualification semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING, NoReturn, Protocol

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.strategy.errors import OnlyQualificationError
from onlyalpha.strategy.freeze_relation import OnlyStrategyFreezeRelation
from onlyalpha.strategy.store import OnlyStrategyRevisionReader

if TYPE_CHECKING:
    from onlyalpha.backtest.evidence import OnlyBacktestEvidenceManifest
    from onlyalpha.research.result.result import OnlyResearchResult


class OnlyQualificationGate(StrEnum):
    RESEARCH_TO_BACKTEST = "RESEARCH_TO_BACKTEST"
    BACKTEST_TO_SIM = "BACKTEST_TO_SIM"


class OnlyQualificationEvidenceKind(StrEnum):
    RESEARCH_RESULT = "RESEARCH_RESULT"
    BACKTEST_EVIDENCE = "BACKTEST_EVIDENCE"


class OnlyQualificationOutcome(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OnlyQualificationCriterionOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, order=True, slots=True)
class OnlyQualificationCriterion:
    criterion_id: str
    evidence_kind: OnlyQualificationEvidenceKind
    metric: str
    comparison: str
    threshold: Decimal

    def __post_init__(self) -> None:
        if not self.criterion_id.strip() or not self.metric.strip() or not self.comparison.strip():
            raise ValueError("Qualification criterion identity and semantics are required")
        if not isinstance(self.evidence_kind, OnlyQualificationEvidenceKind):
            raise ValueError("Qualification criterion evidence kind is invalid")
        if not isinstance(self.threshold, Decimal) or not self.threshold.is_finite():
            raise ValueError("Qualification criterion threshold must be a finite Decimal")

    def to_dict(self) -> dict[str, object]:
        return {
            "criterion_id": self.criterion_id,
            "evidence_kind": self.evidence_kind.value,
            "metric": self.metric,
            "comparison": self.comparison,
            "threshold": _decimal_text(self.threshold),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyQualificationCriterion:
        _exact(payload, {"criterion_id", "evidence_kind", "metric", "comparison", "threshold"}, "criterion")
        return cls(
            _string(payload, "criterion_id"),
            OnlyQualificationEvidenceKind(_string(payload, "evidence_kind")),
            _string(payload, "metric"),
            _string(payload, "comparison"),
            _decimal(payload, "threshold"),
        )


@dataclass(frozen=True, slots=True)
class OnlyQualificationPolicyRevision:
    policy_id: str
    policy_version: str
    gate: OnlyQualificationGate
    criteria: tuple[OnlyQualificationCriterion, ...]
    missing_evidence_behavior: str = "FAIL"
    aggregation: str = "ALL"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Qualification Policy schema")
        _identifier(self.policy_id, "policy_id")
        _positive_version(self.policy_version)
        if not isinstance(self.gate, OnlyQualificationGate):
            raise ValueError("Qualification Policy gate is invalid")
        canonical = tuple(sorted(self.criteria, key=lambda item: item.criterion_id))
        if (
            not canonical
            or canonical != self.criteria
            or len({item.criterion_id for item in canonical}) != len(canonical)
        ):
            raise ValueError("Qualification Policy criteria must be canonical, non-empty and unique")
        if not self.missing_evidence_behavior.strip() or not self.aggregation.strip():
            raise ValueError("Qualification Policy behavior is required")

    @property
    def policy_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.strategy.qualification-policy", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "gate": self.gate.value,
            "criteria": [item.to_dict() for item in self.criteria],
            "missing_evidence_behavior": self.missing_evidence_behavior,
            "aggregation": self.aggregation,
        }
        if include_fingerprint:
            payload["policy_fingerprint"] = self.policy_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyQualificationPolicyRevision:
        _exact(
            payload,
            {
                "schema_version",
                "policy_id",
                "policy_version",
                "gate",
                "criteria",
                "missing_evidence_behavior",
                "aggregation",
                "policy_fingerprint",
            },
            "policy",
        )
        raw = payload["criteria"]
        if not isinstance(raw, list):
            raise ValueError("Qualification Policy criteria must be an array")
        policy = cls(
            _string(payload, "policy_id"),
            _string(payload, "policy_version"),
            OnlyQualificationGate(_string(payload, "gate")),
            tuple(OnlyQualificationCriterion.from_dict(_mapping(item, "criterion")) for item in raw),
            _string(payload, "missing_evidence_behavior"),
            _string(payload, "aggregation"),
            _integer(payload, "schema_version"),
        )
        if payload["policy_fingerprint"] != policy.policy_fingerprint:
            raise ValueError("Qualification Policy identity differs")
        return policy


@dataclass(frozen=True, order=True, slots=True)
class OnlyQualificationEvidenceReference:
    kind: OnlyQualificationEvidenceKind
    evidence_fingerprint: str
    locator_fingerprint: str | None = None
    subject_binding_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, OnlyQualificationEvidenceKind):
            raise ValueError("Qualification Evidence kind is invalid")
        _sha(self.evidence_fingerprint, "Qualification Evidence fingerprint")
        for name, value in (
            ("Qualification Evidence locator", self.locator_fingerprint),
            ("Qualification subject binding", self.subject_binding_fingerprint),
        ):
            if value is not None:
                _sha(value, name)
        if self.kind is OnlyQualificationEvidenceKind.RESEARCH_RESULT:
            if self.locator_fingerprint is None or self.subject_binding_fingerprint is None:
                raise ValueError("Research Qualification Evidence requires exact Result locator and Freeze relation")
        elif self.locator_fingerprint is not None or self.subject_binding_fingerprint is not None:
            raise ValueError("Backtest Qualification Evidence does not accept Research bindings")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "evidence_fingerprint": self.evidence_fingerprint,
            "locator_fingerprint": self.locator_fingerprint,
            "subject_binding_fingerprint": self.subject_binding_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyQualificationEvidenceReference:
        _exact(
            payload,
            {"kind", "evidence_fingerprint", "locator_fingerprint", "subject_binding_fingerprint"},
            "evidence reference",
        )
        return cls(
            OnlyQualificationEvidenceKind(_string(payload, "kind")),
            _string(payload, "evidence_fingerprint"),
            _optional_string(payload, "locator_fingerprint"),
            _optional_string(payload, "subject_binding_fingerprint"),
        )


@dataclass(frozen=True, order=True, slots=True)
class OnlyQualificationCriterionResult:
    criterion_id: str
    source_evidence_fingerprint: str
    metric: str
    observed_value: Decimal
    comparison: str
    threshold: Decimal
    outcome: OnlyQualificationCriterionOutcome

    def __post_init__(self) -> None:
        if not self.criterion_id.strip() or not self.metric.strip() or not self.comparison.strip():
            raise ValueError("Qualification Criterion Result semantics are required")
        _sha(self.source_evidence_fingerprint, "Qualification Criterion source Evidence")
        if not self.observed_value.is_finite() or not self.threshold.is_finite():
            raise ValueError("Qualification Criterion Result values must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "criterion_id": self.criterion_id,
            "source_evidence_fingerprint": self.source_evidence_fingerprint,
            "metric": self.metric,
            "observed_value": _decimal_text(self.observed_value),
            "comparison": self.comparison,
            "threshold": _decimal_text(self.threshold),
            "outcome": self.outcome.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyQualificationCriterionResult:
        _exact(
            payload,
            {
                "criterion_id",
                "source_evidence_fingerprint",
                "metric",
                "observed_value",
                "comparison",
                "threshold",
                "outcome",
            },
            "criterion result",
        )
        return cls(
            _string(payload, "criterion_id"),
            _string(payload, "source_evidence_fingerprint"),
            _string(payload, "metric"),
            _decimal(payload, "observed_value"),
            _string(payload, "comparison"),
            _decimal(payload, "threshold"),
            OnlyQualificationCriterionOutcome(_string(payload, "outcome")),
        )


@dataclass(frozen=True, slots=True)
class OnlyQualificationDecision:
    subject_strategy_fingerprint: str
    gate: OnlyQualificationGate
    policy_id: str
    policy_version: str
    policy_fingerprint: str
    evidence: tuple[OnlyQualificationEvidenceReference, ...]
    criterion_results: tuple[OnlyQualificationCriterionResult, ...]
    outcome: OnlyQualificationOutcome
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Qualification Decision schema")
        _sha(self.subject_strategy_fingerprint, "Qualification subject")
        _identifier(self.policy_id, "policy_id")
        _positive_version(self.policy_version)
        _sha(self.policy_fingerprint, "Qualification Policy fingerprint")
        if not self.evidence or self.evidence != tuple(sorted(self.evidence)):
            raise ValueError("Qualification Decision Evidence must be canonical and non-empty")
        if not self.criterion_results or self.criterion_results != tuple(
            sorted(self.criterion_results, key=lambda item: item.criterion_id)
        ):
            raise ValueError("Qualification Decision results must be canonical and non-empty")

    @property
    def decision_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.strategy.qualification-decision", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "subject_strategy_fingerprint": self.subject_strategy_fingerprint,
            "gate": self.gate.value,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "evidence": [item.to_dict() for item in self.evidence],
            "criterion_results": [item.to_dict() for item in self.criterion_results],
            "outcome": self.outcome.value,
        }
        if include_fingerprint:
            payload["decision_fingerprint"] = self.decision_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyQualificationDecision:
        _exact(
            payload,
            {
                "schema_version",
                "subject_strategy_fingerprint",
                "gate",
                "policy_id",
                "policy_version",
                "policy_fingerprint",
                "evidence",
                "criterion_results",
                "outcome",
                "decision_fingerprint",
            },
            "decision",
        )
        raw_evidence = payload["evidence"]
        raw_results = payload["criterion_results"]
        if not isinstance(raw_evidence, list) or not isinstance(raw_results, list):
            raise ValueError("Qualification Decision evidence/results must be arrays")
        decision = cls(
            _string(payload, "subject_strategy_fingerprint"),
            OnlyQualificationGate(_string(payload, "gate")),
            _string(payload, "policy_id"),
            _string(payload, "policy_version"),
            _string(payload, "policy_fingerprint"),
            tuple(OnlyQualificationEvidenceReference.from_dict(_mapping(item, "evidence")) for item in raw_evidence),
            tuple(OnlyQualificationCriterionResult.from_dict(_mapping(item, "result")) for item in raw_results),
            OnlyQualificationOutcome(_string(payload, "outcome")),
            _integer(payload, "schema_version"),
        )
        if payload["decision_fingerprint"] != decision.decision_fingerprint:
            raise ValueError("Qualification Decision identity differs")
        return decision


class OnlyQualificationPolicyReader(Protocol):
    def load_exact(self, policy_id: str, policy_version: str) -> OnlyQualificationPolicyRevision: ...


@dataclass(frozen=True, slots=True)
class _OnlyQualificationDecisionPublication:
    decision: OnlyQualificationDecision
    seal: object


_QUALIFICATION_DECISION_PUBLICATION_SEAL = object()


def _only_authorize_qualification_decision_publication(
    decision: OnlyQualificationDecision,
) -> _OnlyQualificationDecisionPublication:
    """Seal one evaluator-produced Decision for the internal publisher capability."""

    return _OnlyQualificationDecisionPublication(decision, _QUALIFICATION_DECISION_PUBLICATION_SEAL)


class OnlyQualificationDecisionAuthority(Protocol):
    def publish_verified(self, publication: _OnlyQualificationDecisionPublication) -> OnlyQualificationDecision: ...

    def load_verified(self, decision_fingerprint: str) -> OnlyQualificationDecision: ...


class _ResearchResultReader(Protocol):
    def load_verified(self, research_result_plan_fingerprint: str) -> OnlyResearchResult: ...


class _BacktestEvidenceReader(Protocol):
    def load_verified(self, evidence_fingerprint: str) -> OnlyBacktestEvidenceManifest: ...


class _FreezeRelationReader(OnlyStrategyRevisionReader, Protocol):
    def load_freeze_relation(self, relation_fingerprint: str) -> OnlyStrategyFreezeRelation: ...


class OnlyQualificationEvaluator:
    """Sole deterministic constructor of Qualification Decision facts."""

    def __init__(
        self,
        *,
        strategies: _FreezeRelationReader,
        policies: OnlyQualificationPolicyReader,
        research_results: _ResearchResultReader,
        backtest_evidence: _BacktestEvidenceReader,
        decisions: OnlyQualificationDecisionAuthority,
    ) -> None:
        self._strategies = strategies
        self._policies = policies
        self._research_results = research_results
        self._backtest_evidence = backtest_evidence
        self._decisions = decisions

    def evaluate(
        self,
        *,
        subject_strategy_fingerprint: str,
        policy_id: str,
        policy_version: str,
        evidence: tuple[OnlyQualificationEvidenceReference, ...],
    ) -> OnlyQualificationDecision:
        self._load_subject(subject_strategy_fingerprint)
        policy = self._load_policy(policy_id, policy_version)
        if policy.missing_evidence_behavior != "FAIL" or policy.aggregation != "ALL":
            _fail("QUALIFICATION_POLICY_UNSUPPORTED", policy.policy_fingerprint)
        expected_kind = _evidence_kind(policy.gate)
        if len(evidence) != 1 or evidence[0].kind is not expected_kind:
            _fail("QUALIFICATION_EVIDENCE_GATE_MISMATCH", policy.gate.value)
        canonical_evidence = tuple(sorted(evidence))
        metrics = self._metrics(subject_strategy_fingerprint, canonical_evidence[0])
        results: list[OnlyQualificationCriterionResult] = []
        for criterion in policy.criteria:
            if criterion.evidence_kind is not expected_kind:
                _fail("QUALIFICATION_EVIDENCE_GATE_MISMATCH", criterion.criterion_id)
            observed = metrics.get(criterion.metric)
            if observed is None:
                supported = criterion.metric in _SUPPORTED_METRICS
                _fail(
                    "QUALIFICATION_REQUIRED_EVIDENCE_MISSING" if supported else "QUALIFICATION_POLICY_UNSUPPORTED",
                    criterion.metric,
                )
            passed = _compare(observed, criterion.comparison, criterion.threshold)
            results.append(
                OnlyQualificationCriterionResult(
                    criterion.criterion_id,
                    canonical_evidence[0].evidence_fingerprint,
                    criterion.metric,
                    observed,
                    criterion.comparison,
                    criterion.threshold,
                    OnlyQualificationCriterionOutcome.PASS if passed else OnlyQualificationCriterionOutcome.FAIL,
                )
            )
        decision = OnlyQualificationDecision(
            subject_strategy_fingerprint,
            policy.gate,
            policy.policy_id,
            policy.policy_version,
            policy.policy_fingerprint,
            canonical_evidence,
            tuple(results),
            (
                OnlyQualificationOutcome.APPROVED
                if all(item.outcome is OnlyQualificationCriterionOutcome.PASS for item in results)
                else OnlyQualificationOutcome.REJECTED
            ),
        )
        return self._decisions.publish_verified(_only_authorize_qualification_decision_publication(decision))

    def replay(self, decision_fingerprint: str) -> OnlyQualificationDecision:
        try:
            original = self._decisions.load_verified(decision_fingerprint)
        except Exception as exc:
            _fail("QUALIFICATION_DECISION_CORRUPT", decision_fingerprint, exc)
        replayed = self.evaluate(
            subject_strategy_fingerprint=original.subject_strategy_fingerprint,
            policy_id=original.policy_id,
            policy_version=original.policy_version,
            evidence=original.evidence,
        )
        if replayed != original or replayed.decision_fingerprint != decision_fingerprint:
            _fail("QUALIFICATION_DECISION_CORRUPT", decision_fingerprint)
        return replayed

    def _load_subject(self, fingerprint: str) -> None:
        try:
            subject = self._strategies.load_verified(fingerprint)
        except Exception as exc:
            _fail(str(getattr(exc, "code", "STRATEGY_NOT_FOUND")), fingerprint, exc)
        if str(subject.strategy_fingerprint) != fingerprint:
            _fail("QUALIFICATION_DECISION_SUBJECT_MISMATCH", fingerprint)

    def _load_policy(self, policy_id: str, policy_version: str) -> OnlyQualificationPolicyRevision:
        try:
            return self._policies.load_exact(policy_id, policy_version)
        except OnlyQualificationError:
            raise
        except Exception as exc:
            _fail("QUALIFICATION_POLICY_NOT_FOUND", f"{policy_id}@{policy_version}", exc)

    def _metrics(self, subject: str, evidence: OnlyQualificationEvidenceReference) -> dict[str, Decimal]:
        if evidence.kind is OnlyQualificationEvidenceKind.RESEARCH_RESULT:
            assert evidence.locator_fingerprint is not None
            assert evidence.subject_binding_fingerprint is not None
            try:
                relation = self._strategies.load_freeze_relation(evidence.subject_binding_fingerprint)
            except Exception as exc:
                _fail("QUALIFICATION_EVIDENCE_NOT_FOUND", evidence.subject_binding_fingerprint, exc)
            if (
                relation.strategy_fingerprint != subject
                or relation.research_result_fingerprint != evidence.evidence_fingerprint
            ):
                _fail("QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH", evidence.evidence_fingerprint)
            try:
                result = self._research_results.load_verified(evidence.locator_fingerprint)
            except Exception as exc:
                _fail("QUALIFICATION_EVIDENCE_NOT_FOUND", evidence.evidence_fingerprint, exc)
            research_manifest = result.manifest
            if research_manifest.research_result_fingerprint != evidence.evidence_fingerprint:
                _fail("QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH", evidence.evidence_fingerprint)
            return {
                "research.statistics_result_count": Decimal(len(research_manifest.statistics_results)),
                "research.calculation_result_count": Decimal(len(research_manifest.calculation_results)),
            }
        try:
            backtest_manifest = self._backtest_evidence.load_verified(evidence.evidence_fingerprint)
        except Exception as exc:
            _fail("QUALIFICATION_EVIDENCE_NOT_FOUND", evidence.evidence_fingerprint, exc)
        if backtest_manifest.strategy_fingerprint != subject:
            _fail("QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH", evidence.evidence_fingerprint)
        return {
            "backtest.artifact_count": Decimal(len(backtest_manifest.artifacts)),
            "backtest.implementation_count": Decimal(len(backtest_manifest.implementation_fingerprints)),
        }


_SUPPORTED_METRICS = {
    "research.statistics_result_count",
    "research.calculation_result_count",
    "backtest.artifact_count",
    "backtest.implementation_count",
}


def _evidence_kind(gate: OnlyQualificationGate) -> OnlyQualificationEvidenceKind:
    return (
        OnlyQualificationEvidenceKind.RESEARCH_RESULT
        if gate is OnlyQualificationGate.RESEARCH_TO_BACKTEST
        else OnlyQualificationEvidenceKind.BACKTEST_EVIDENCE
    )


def _compare(observed: Decimal, comparison: str, threshold: Decimal) -> bool:
    if comparison == "GT":
        return observed > threshold
    if comparison == "GE":
        return observed >= threshold
    if comparison == "EQ":
        return observed == threshold
    if comparison == "LE":
        return observed <= threshold
    if comparison == "LT":
        return observed < threshold
    _fail("QUALIFICATION_POLICY_UNSUPPORTED", comparison)


def _fail(code: str, detail: str, cause: Exception | None = None) -> NoReturn:
    error = OnlyQualificationError(code, detail)
    if cause is not None:
        raise error from cause
    raise error


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _decimal(payload: Mapping[str, object], key: str) -> Decimal:
    raw = _string(payload, key)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Qualification {key} must be a Decimal string") from exc
    if not value.is_finite() or _decimal_text(value) != raw:
        raise ValueError(f"Qualification {key} must be a canonical Decimal string")
    return value


def _identifier(value: str, name: str) -> None:
    if not value or len(value) > 128 or value[0] not in "abcdefghijklmnopqrstuvwxyz0123456789":
        raise ValueError(f"Qualification {name} is invalid")
    if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for char in value):
        raise ValueError(f"Qualification {name} is invalid")


def _positive_version(value: str) -> None:
    if not value.isdigit() or value.startswith("0") or int(value) <= 0:
        raise ValueError("Qualification policy_version must be a positive integer string")


def _sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Qualification {name} must be an object")
    return value


def _exact(payload: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"Qualification {name} fields are invalid")


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"Qualification {key} must be a string")
    return value


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload[key]
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Qualification {key} must be a string or null")
    return value


def _integer(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Qualification {key} must be an integer")
    return value


__all__ = [name for name in globals() if name.startswith("Only")]
