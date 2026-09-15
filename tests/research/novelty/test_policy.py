from __future__ import annotations

import json
from dataclasses import fields, replace

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.novelty import (
    OnlyNoveltyPolicyCondition,
    OnlyNoveltyPolicyConflictError,
    OnlyNoveltyPolicyCorruptError,
    OnlyNoveltyPolicyInvalidError,
    OnlyNoveltyPolicyNotFoundError,
    OnlyNoveltyPolicyOutcome,
    OnlyNoveltyPolicyRevisionV1,
    OnlyNoveltyPolicyRuleV1,
    OnlyNoveltyPolicySchemaUnsupportedError,
    OnlyNoveltyPolicyStore,
)


def policy(**overrides: OnlyNoveltyPolicyOutcome) -> OnlyNoveltyPolicyRevisionV1:
    outcomes = {
        "EXACT_COMPLETED_EVALUATION": OnlyNoveltyPolicyOutcome.REUSE,
        "CERTIFIED_NO_MATCH": OnlyNoveltyPolicyOutcome.ADMIT,
        "EXACT_COMPLETED_NEGATIVE_EVIDENCE": OnlyNoveltyPolicyOutcome.SUPPRESS,
        "PROOF_INCOMPLETE": OnlyNoveltyPolicyOutcome.FAIL_CLOSED,
        "PROOF_UNAVAILABLE": OnlyNoveltyPolicyOutcome.FAIL_CLOSED,
        "OPERATIONAL_FAILURE": OnlyNoveltyPolicyOutcome.REVIEW,
        "SEARCH_OR_BUDGET_STOP": OnlyNoveltyPolicyOutcome.REVIEW,
        **overrides,
    }
    rules = tuple(
        sorted(
            (
                OnlyNoveltyPolicyRuleV1(OnlyNoveltyPolicyCondition(condition), outcome)
                for condition, outcome in outcomes.items()
            ),
            key=lambda rule: rule.condition.value,
        )
    )
    return OnlyNoveltyPolicyRevisionV1("default-novelty", "1", rules)


def test_policy_identity_is_canonical_and_semantic_changes_change_fingerprint() -> None:
    first = policy()
    second = policy()
    assert first.to_dict() == second.to_dict()
    assert first.policy_fingerprint == second.policy_fingerprint
    for changed in (
        policy(EXACT_COMPLETED_EVALUATION=OnlyNoveltyPolicyOutcome.ADMIT),
        policy(EXACT_COMPLETED_NEGATIVE_EVIDENCE=OnlyNoveltyPolicyOutcome.REVIEW),
        policy(PROOF_INCOMPLETE=OnlyNoveltyPolicyOutcome.REVIEW),
    ):
        assert changed.policy_fingerprint != first.policy_fingerprint


def test_policy_round_trip_has_stable_canonical_bytes() -> None:
    original = policy()
    serialized = only_canonical_json(original.to_dict())
    loaded = OnlyNoveltyPolicyRevisionV1.from_dict(json.loads(serialized))
    assert loaded == original
    assert only_canonical_json(loaded.to_dict()) == serialized


@pytest.mark.parametrize("schema_version", [True, 1.0, 2])
def test_malformed_or_unsupported_schema_is_rejected(schema_version: object) -> None:
    with pytest.raises(OnlyNoveltyPolicySchemaUnsupportedError):
        replace(policy(), schema_version=schema_version)  # type: ignore[arg-type]


@pytest.mark.parametrize("version", ["", "0", "-1", "1.0", 1, True])
def test_invalid_policy_version_is_rejected(version: object) -> None:
    with pytest.raises(OnlyNoveltyPolicyInvalidError):
        replace(policy(), policy_version=version)  # type: ignore[arg-type]


@pytest.mark.parametrize("policy_id", ["", "has space", "../escape", "/absolute"])
def test_invalid_policy_identity_is_rejected(policy_id: str) -> None:
    with pytest.raises(OnlyNoveltyPolicyInvalidError):
        replace(policy(), policy_id=policy_id)


def test_duplicate_and_contradictory_rules_are_rejected() -> None:
    original = policy()
    duplicate = tuple(sorted((*original.rules[:-1], original.rules[0]), key=lambda rule: rule.condition.value))
    with pytest.raises(OnlyNoveltyPolicyInvalidError, match="duplicate or contradictory"):
        replace(original, rules=duplicate)
    contradictory = tuple(
        sorted(
            (*original.rules, OnlyNoveltyPolicyRuleV1(original.rules[0].condition, OnlyNoveltyPolicyOutcome.REVIEW)),
            key=lambda rule: rule.condition.value,
        )
    )
    with pytest.raises(OnlyNoveltyPolicyInvalidError, match="duplicate or contradictory"):
        replace(original, rules=contradictory)


def test_missing_rule_and_nested_rule_shape_are_rejected() -> None:
    original = policy()
    with pytest.raises(OnlyNoveltyPolicyInvalidError, match="exactly one rule"):
        replace(original, rules=original.rules[:-1])
    payload = original.to_dict()
    rules = payload["rules"]
    assert isinstance(rules, list) and isinstance(rules[0], dict)
    rules[0]["unexpected"] = True
    with pytest.raises(OnlyNoveltyPolicyInvalidError, match="fields are invalid"):
        OnlyNoveltyPolicyRevisionV1.from_dict(payload)


@pytest.mark.parametrize(
    ("condition", "outcome"),
    [
        (OnlyNoveltyPolicyCondition.PROOF_INCOMPLETE, OnlyNoveltyPolicyOutcome.ADMIT),
        (OnlyNoveltyPolicyCondition.PROOF_UNAVAILABLE, OnlyNoveltyPolicyOutcome.ADMIT),
        (OnlyNoveltyPolicyCondition.OPERATIONAL_FAILURE, OnlyNoveltyPolicyOutcome.SUPPRESS),
        (OnlyNoveltyPolicyCondition.SEARCH_OR_BUDGET_STOP, OnlyNoveltyPolicyOutcome.SUPPRESS),
    ],
)
def test_unsafe_fact_interpretation_is_impossible(
    condition: OnlyNoveltyPolicyCondition, outcome: OnlyNoveltyPolicyOutcome
) -> None:
    with pytest.raises(OnlyNoveltyPolicyInvalidError, match="unsafe rule"):
        OnlyNoveltyPolicyRuleV1(condition, outcome)


@pytest.mark.parametrize(
    "rule",
    [
        {"condition": "APPROXIMATE_SIMILARITY", "outcome": "REUSE"},
        {"condition": "CERTIFIED_NO_MATCH", "outcome": "NOVEL"},
    ],
)
def test_unknown_or_approximate_rule_vocabulary_is_rejected(rule: dict[str, str]) -> None:
    payload = policy().to_dict()
    rules = payload["rules"]
    assert isinstance(rules, list)
    rules[0] = rule
    with pytest.raises(OnlyNoveltyPolicyInvalidError, match="unknown"):
        OnlyNoveltyPolicyRevisionV1.from_dict(payload)


def test_store_is_put_once_and_exact_loadable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = OnlyNoveltyPolicyStore(tmp_path)
    original = policy()
    assert store.put(original) == original
    assert store.put(original) == original
    assert OnlyNoveltyPolicyStore(tmp_path).load_exact("default-novelty", "1") == original

    changed = policy(EXACT_COMPLETED_EVALUATION=OnlyNoveltyPolicyOutcome.ADMIT)
    with pytest.raises(OnlyNoveltyPolicyConflictError):
        store.put(changed)


def test_store_missing_revision_is_explicit(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(OnlyNoveltyPolicyNotFoundError):
        OnlyNoveltyPolicyStore(tmp_path).load_exact("default-novelty", "1")


def test_store_revalidates_and_never_persists_a_mutated_policy(tmp_path) -> None:  # type: ignore[no-untyped-def]
    malformed = policy()
    object.__setattr__(malformed, "rules", malformed.rules[:-1])
    store = OnlyNoveltyPolicyStore(tmp_path)
    with pytest.raises(OnlyNoveltyPolicyInvalidError, match="exactly one rule"):
        store.put(malformed)
    with pytest.raises(OnlyNoveltyPolicyNotFoundError):
        store.load_exact("default-novelty", "1")


@pytest.mark.parametrize("mutation", ["content", "fingerprint", "noncanonical", "extra-entry"])
def test_store_corruption_fails_closed(tmp_path, mutation: str) -> None:  # type: ignore[no-untyped-def]
    store = OnlyNoveltyPolicyStore(tmp_path)
    original = store.put(policy())
    revision = tmp_path / "research" / "novelty-policies" / original.policy_id / original.policy_version
    manifest = revision / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if mutation == "content":
        payload["policy_id"] = "different"
        manifest.write_text(only_canonical_json(payload), encoding="utf-8")
    elif mutation == "fingerprint":
        payload["policy_fingerprint"] = "0" * 64
        manifest.write_text(only_canonical_json(payload), encoding="utf-8")
    elif mutation == "noncanonical":
        manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        (revision / "unexpected").write_text("", encoding="utf-8")
    with pytest.raises(OnlyNoveltyPolicyCorruptError):
        store.load_exact(original.policy_id, original.policy_version)


def test_store_unsupported_schema_is_explicit(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = OnlyNoveltyPolicyStore(tmp_path)
    original = store.put(policy())
    manifest = tmp_path / "research" / "novelty-policies" / original.policy_id / "1" / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    manifest.write_text(only_canonical_json(payload), encoding="utf-8")
    with pytest.raises(OnlyNoveltyPolicySchemaUnsupportedError):
        store.load_exact(original.policy_id, original.policy_version)


def test_store_rejects_unsafe_authority_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    outside = tmp_path / "outside"
    outside.mkdir()
    research = tmp_path / "research"
    research.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OnlyNoveltyPolicyCorruptError, match="unsafe authority path"):
        OnlyNoveltyPolicyStore(tmp_path).put(policy())


def test_policy_has_no_scientific_fact_or_decision_occurrence_fields() -> None:
    names = {field.name for field in fields(OnlyNoveltyPolicyRevisionV1)}
    assert names == {"policy_id", "policy_version", "rules", "schema_version"}
