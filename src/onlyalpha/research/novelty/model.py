"""Immutable Novelty Policy rule authority."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn, cast

from onlyalpha.canonical import only_canonical_fingerprint

NOVELTY_POLICY_SCHEMA_VERSION = 1

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VERSION = re.compile(r"^[1-9][0-9]{0,127}$")


class OnlyNoveltyPolicyError(RuntimeError):
    code = "NOVELTY_POLICY_ERROR"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class OnlyNoveltyPolicyInvalidError(OnlyNoveltyPolicyError):
    code = "NOVELTY_POLICY_INVALID"


class OnlyNoveltyPolicySchemaUnsupportedError(OnlyNoveltyPolicyError):
    code = "NOVELTY_POLICY_SCHEMA_UNSUPPORTED"


class OnlyNoveltyPolicyOutcome(StrEnum):
    ADMIT = "ADMIT"
    REUSE = "REUSE"
    SUPPRESS = "SUPPRESS"
    REVIEW = "REVIEW"
    FAIL_CLOSED = "FAIL_CLOSED"


class OnlyNoveltyPolicyCondition(StrEnum):
    EXACT_COMPLETED_EVALUATION = "EXACT_COMPLETED_EVALUATION"
    CERTIFIED_NO_MATCH = "CERTIFIED_NO_MATCH"
    EXACT_COMPLETED_NEGATIVE_EVIDENCE = "EXACT_COMPLETED_NEGATIVE_EVIDENCE"
    PROOF_INCOMPLETE = "PROOF_INCOMPLETE"
    PROOF_UNAVAILABLE = "PROOF_UNAVAILABLE"
    OPERATIONAL_FAILURE = "OPERATIONAL_FAILURE"
    SEARCH_OR_BUDGET_STOP = "SEARCH_OR_BUDGET_STOP"


_ALLOWED_OUTCOMES = {
    OnlyNoveltyPolicyCondition.EXACT_COMPLETED_EVALUATION: frozenset(
        {OnlyNoveltyPolicyOutcome.REUSE, OnlyNoveltyPolicyOutcome.ADMIT, OnlyNoveltyPolicyOutcome.REVIEW}
    ),
    OnlyNoveltyPolicyCondition.CERTIFIED_NO_MATCH: frozenset(
        {OnlyNoveltyPolicyOutcome.ADMIT, OnlyNoveltyPolicyOutcome.REVIEW, OnlyNoveltyPolicyOutcome.FAIL_CLOSED}
    ),
    OnlyNoveltyPolicyCondition.EXACT_COMPLETED_NEGATIVE_EVIDENCE: frozenset(
        {OnlyNoveltyPolicyOutcome.SUPPRESS, OnlyNoveltyPolicyOutcome.REVIEW, OnlyNoveltyPolicyOutcome.FAIL_CLOSED}
    ),
    OnlyNoveltyPolicyCondition.PROOF_INCOMPLETE: frozenset(
        {OnlyNoveltyPolicyOutcome.REVIEW, OnlyNoveltyPolicyOutcome.FAIL_CLOSED}
    ),
    OnlyNoveltyPolicyCondition.PROOF_UNAVAILABLE: frozenset(
        {OnlyNoveltyPolicyOutcome.REVIEW, OnlyNoveltyPolicyOutcome.FAIL_CLOSED}
    ),
    OnlyNoveltyPolicyCondition.OPERATIONAL_FAILURE: frozenset(
        {OnlyNoveltyPolicyOutcome.REVIEW, OnlyNoveltyPolicyOutcome.FAIL_CLOSED}
    ),
    OnlyNoveltyPolicyCondition.SEARCH_OR_BUDGET_STOP: frozenset(
        {OnlyNoveltyPolicyOutcome.REVIEW, OnlyNoveltyPolicyOutcome.FAIL_CLOSED}
    ),
}


def _invalid(detail: str) -> NoReturn:
    raise OnlyNoveltyPolicyInvalidError(detail)


def _policy_id(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        _invalid("policy_id must be a path-safe non-empty identifier")
    return value


def _policy_version(value: object) -> str:
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        _invalid("policy_version must be a positive integer string")
    return value


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        _invalid(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _string(value: object, context: str) -> str:
    if not isinstance(value, str):
        _invalid(f"{context} must be a string")
    return value


def _exact(payload: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(payload) != expected:
        _invalid(f"{context} fields are invalid")


@dataclass(frozen=True, order=True, slots=True)
class OnlyNoveltyPolicyRuleV1:
    condition: OnlyNoveltyPolicyCondition
    outcome: OnlyNoveltyPolicyOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.condition, OnlyNoveltyPolicyCondition) or not isinstance(
            self.outcome, OnlyNoveltyPolicyOutcome
        ):
            _invalid("rule condition and outcome must use the V1 typed vocabulary")
        if self.outcome not in _ALLOWED_OUTCOMES[self.condition]:
            _invalid(f"unsafe rule {self.condition.value} -> {self.outcome.value}")

    def to_dict(self) -> dict[str, str]:
        return {"condition": self.condition.value, "outcome": self.outcome.value}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNoveltyPolicyRuleV1:
        _exact(payload, {"condition", "outcome"}, "Novelty Policy rule")
        try:
            return cls(
                OnlyNoveltyPolicyCondition(_string(payload["condition"], "condition")),
                OnlyNoveltyPolicyOutcome(_string(payload["outcome"], "outcome")),
            )
        except (TypeError, ValueError) as exc:
            raise OnlyNoveltyPolicyInvalidError("unknown Novelty Policy rule value") from exc


@dataclass(frozen=True, slots=True)
class OnlyNoveltyPolicyRevisionV1:
    policy_id: str
    policy_version: str
    rules: tuple[OnlyNoveltyPolicyRuleV1, ...]
    schema_version: int = NOVELTY_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != NOVELTY_POLICY_SCHEMA_VERSION
        ):
            raise OnlyNoveltyPolicySchemaUnsupportedError(str(self.schema_version))
        _policy_id(self.policy_id)
        _policy_version(self.policy_version)
        if any(not isinstance(rule, OnlyNoveltyPolicyRuleV1) for rule in self.rules):
            _invalid("rules must use the V1 typed vocabulary")
        expected = tuple(sorted(self.rules, key=lambda rule: rule.condition.value))
        if self.rules != expected:
            _invalid("rules must use canonical condition order")
        conditions = tuple(rule.condition for rule in self.rules)
        if len(set(conditions)) != len(conditions):
            _invalid("duplicate or contradictory semantic rule")
        if set(conditions) != set(OnlyNoveltyPolicyCondition):
            _invalid("V1 requires exactly one rule for every condition")

    @property
    def policy_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.novelty-policy", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "rules": [rule.to_dict() for rule in self.rules],
        }
        if include_fingerprint:
            payload["policy_fingerprint"] = self.policy_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyNoveltyPolicyRevisionV1:
        _exact(payload, {"schema_version", "policy_id", "policy_version", "rules", "policy_fingerprint"}, "Policy")
        schema_version = payload["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != NOVELTY_POLICY_SCHEMA_VERSION
        ):
            raise OnlyNoveltyPolicySchemaUnsupportedError(str(schema_version))
        raw_rules = payload["rules"]
        if not isinstance(raw_rules, list):
            _invalid("rules must be an array")
        policy = cls(
            _policy_id(payload["policy_id"]),
            _policy_version(payload["policy_version"]),
            tuple(OnlyNoveltyPolicyRuleV1.from_dict(_mapping(rule, "rule")) for rule in raw_rules),
            schema_version,
        )
        if payload["policy_fingerprint"] != policy.policy_fingerprint:
            _invalid("policy content fingerprint mismatch")
        return policy


__all__ = [name for name in globals() if name.startswith(("NOVELTY_", "OnlyNovelty"))]
