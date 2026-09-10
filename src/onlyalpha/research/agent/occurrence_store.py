"""Crash-safe put-once stores and immutable locators for Agent occurrences."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.canonical import only_canonical_fingerprint

from .errors import OnlyAgentContextStoreError
from .occurrence import (
    OnlyAgentModelCallPlanV1,
    OnlyAgentModelCallResultV1,
    OnlyAgentToolCallPlanV1,
    OnlyAgentToolCallResultV1,
)
from .store import OnlyAgentCommitOutcome, _OnlyJsonPutOnceStore


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def _sha(value: object, context: str) -> str:
    result = _string(value, context)
    if len(result) != 64 or any(item not in "0123456789abcdef" for item in result):
        raise ValueError(f"{context} must be a lower-case SHA256")
    return result


class _OccurrenceLocatorKind(StrEnum):
    MODEL_PLAN_BY_SESSION_ORDINAL = "MODEL_PLAN_BY_SESSION_ORDINAL"
    MODEL_RESULT_BY_PLAN = "MODEL_RESULT_BY_PLAN"
    TOOL_PLAN_BY_SESSION_ORDINAL = "TOOL_PLAN_BY_SESSION_ORDINAL"
    TOOL_RESULT_BY_PLAN = "TOOL_RESULT_BY_PLAN"


@dataclass(frozen=True, slots=True)
class _OccurrenceLocatorV1:
    locator_kind: _OccurrenceLocatorKind
    owner_fingerprint: str
    ordinal: int | None
    target_fingerprint: str
    locator_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.locator_kind, _OccurrenceLocatorKind):
            raise ValueError("AGENT_OCCURRENCE_LOCATOR_INVALID")
        _sha(self.owner_fingerprint, "owner_fingerprint")
        _sha(self.target_fingerprint, "target_fingerprint")
        if self.ordinal is not None and self.ordinal < 0:
            raise ValueError("AGENT_OCCURRENCE_LOCATOR_INVALID")
        is_ordinal = self.locator_kind in {
            _OccurrenceLocatorKind.MODEL_PLAN_BY_SESSION_ORDINAL,
            _OccurrenceLocatorKind.TOOL_PLAN_BY_SESSION_ORDINAL,
        }
        if is_ordinal != (self.ordinal is not None):
            raise ValueError("AGENT_OCCURRENCE_LOCATOR_INVALID")
        expected = self.expected_fingerprint(self.locator_kind, self.owner_fingerprint, self.ordinal)
        if not self.locator_fingerprint:
            object.__setattr__(self, "locator_fingerprint", expected)
        elif self.locator_fingerprint != expected:
            raise ValueError("AGENT_OCCURRENCE_LOCATOR_INVALID")

    @staticmethod
    def expected_fingerprint(kind: _OccurrenceLocatorKind, owner: str, ordinal: int | None) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.agent-occurrence-locator",
                "schema_version": 1,
                "locator_kind": kind.value,
                "owner_fingerprint": owner,
                "ordinal": ordinal,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "locator_kind": self.locator_kind.value,
            "owner_fingerprint": self.owner_fingerprint,
            "ordinal": self.ordinal,
            "target_fingerprint": self.target_fingerprint,
            "locator_fingerprint": self.locator_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> _OccurrenceLocatorV1:
        if set(payload) != {
            "schema_version",
            "locator_kind",
            "owner_fingerprint",
            "ordinal",
            "target_fingerprint",
            "locator_fingerprint",
        }:
            raise ValueError("AGENT_OCCURRENCE_LOCATOR_INVALID")
        ordinal = payload["ordinal"]
        return cls(
            _OccurrenceLocatorKind(_string(payload["locator_kind"], "locator_kind")),
            _sha(payload["owner_fingerprint"], "owner_fingerprint"),
            None if ordinal is None else _integer(ordinal, "ordinal"),
            _sha(payload["target_fingerprint"], "target_fingerprint"),
            _sha(payload["locator_fingerprint"], "locator_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


class _OccurrenceStoreHelpers:
    @staticmethod
    def _load_locator(store: _OnlyJsonPutOnceStore, expected: _OccurrenceLocatorV1) -> _OccurrenceLocatorV1:
        value = store.load(
            expected.locator_fingerprint,
            _OccurrenceLocatorV1.from_dict,
            "AGENT_OCCURRENCE_LOCATOR_MISSING",
            "AGENT_OCCURRENCE_LOCATOR_MISMATCH",
        )
        if (
            value.locator_kind is not expected.locator_kind
            or value.owner_fingerprint != expected.owner_fingerprint
            or value.ordinal != expected.ordinal
        ):
            raise OnlyAgentContextStoreError("AGENT_OCCURRENCE_LOCATOR_MISMATCH", expected.locator_fingerprint)
        return value

    @classmethod
    def _load_locator_for(
        cls,
        store: _OnlyJsonPutOnceStore,
        kind: _OccurrenceLocatorKind,
        owner: str,
        ordinal: int | None,
        missing_code: str,
    ) -> _OccurrenceLocatorV1:
        key = _OccurrenceLocatorV1.expected_fingerprint(kind, owner, ordinal)
        value = store.load(key, _OccurrenceLocatorV1.from_dict, missing_code, "AGENT_OCCURRENCE_LOCATOR_MISMATCH")
        if value.locator_kind is not kind or value.owner_fingerprint != owner or value.ordinal != ordinal:
            raise OnlyAgentContextStoreError("AGENT_OCCURRENCE_LOCATOR_MISMATCH", key)
        return value

    @staticmethod
    def _contiguous_count(store: _OnlyJsonPutOnceStore, kind: _OccurrenceLocatorKind, owner: str) -> int:
        ordinal = 0
        while store.exists(
            _OccurrenceLocatorV1.expected_fingerprint(kind, owner, ordinal), "AGENT_OCCURRENCE_LOCATOR_MISSING"
        ):
            ordinal += 1
        return ordinal


class OnlyJsonAgentModelOccurrenceStore(_OccurrenceStoreHelpers):
    def __init__(self, semantic_root: object) -> None:
        from pathlib import Path

        if not isinstance(semantic_root, Path):
            raise TypeError("semantic_root must be a Path")
        self._plans = _OnlyJsonPutOnceStore(semantic_root, Path("research/agent-orchestration/model-calls/plans"))
        self._results = _OnlyJsonPutOnceStore(semantic_root, Path("research/agent-orchestration/model-calls/results"))
        self._ordinal_locators = _OnlyJsonPutOnceStore(
            semantic_root, Path("research/agent-orchestration/model-calls/by-session-ordinal")
        )
        self._result_locators = _OnlyJsonPutOnceStore(
            semantic_root, Path("research/agent-orchestration/model-calls/result-by-plan")
        )

    def commit_plan(self, value: OnlyAgentModelCallPlanV1) -> OnlyAgentCommitOutcome:
        locator = _OccurrenceLocatorV1(
            _OccurrenceLocatorKind.MODEL_PLAN_BY_SESSION_ORDINAL,
            value.agent_session_fingerprint,
            value.call_ordinal,
            value.model_call_plan_fingerprint,
        )
        if self._ordinal_locators.exists(locator.locator_fingerprint, "AGENT_MODEL_CALL_PLAN_INVALID"):
            existing = self._load_locator(self._ordinal_locators, locator)
            if existing.target_fingerprint != value.model_call_plan_fingerprint:
                raise OnlyAgentContextStoreError("AGENT_OCCURRENCE_ORDINAL_CONFLICT", locator.locator_fingerprint)
        elif value.call_ordinal != self.budget_consumed(value.agent_session_fingerprint):
            raise OnlyAgentContextStoreError("AGENT_OCCURRENCE_ORDINAL_CONFLICT", locator.locator_fingerprint)
        outcome = self._plans.commit(
            value.model_call_plan_fingerprint,
            value,
            OnlyAgentModelCallPlanV1.from_dict,
            "AGENT_MODEL_CALL_PLAN_INVALID",
            "AGENT_MODEL_CALL_PLAN_CONFLICT",
        )
        self._ordinal_locators.commit(
            locator.locator_fingerprint,
            locator,
            _OccurrenceLocatorV1.from_dict,
            "AGENT_MODEL_CALL_PLAN_INVALID",
            "AGENT_OCCURRENCE_ORDINAL_CONFLICT",
        )
        return outcome

    def load_plan_verified(self, fingerprint: str) -> OnlyAgentModelCallPlanV1:
        return self._plans.load(
            fingerprint,
            OnlyAgentModelCallPlanV1.from_dict,
            "AGENT_MODEL_CALL_PLAN_INVALID",
            "AGENT_MODEL_CALL_PLAN_CONFLICT",
        )

    def load_plan_by_session_ordinal_verified(self, session_fingerprint: str, ordinal: int) -> OnlyAgentModelCallPlanV1:
        locator = self._load_locator_for(
            self._ordinal_locators,
            _OccurrenceLocatorKind.MODEL_PLAN_BY_SESSION_ORDINAL,
            session_fingerprint,
            ordinal,
            "AGENT_MODEL_CALL_PLAN_INVALID",
        )
        plan = self.load_plan_verified(locator.target_fingerprint)
        if plan.agent_session_fingerprint != session_fingerprint or plan.call_ordinal != ordinal:
            raise OnlyAgentContextStoreError("AGENT_MODEL_CALL_PLAN_CONFLICT", locator.locator_fingerprint)
        return plan

    def commit_result(self, value: OnlyAgentModelCallResultV1) -> OnlyAgentCommitOutcome:
        self.load_plan_verified(value.model_call_plan_fingerprint)
        locator = _OccurrenceLocatorV1(
            _OccurrenceLocatorKind.MODEL_RESULT_BY_PLAN,
            value.model_call_plan_fingerprint,
            None,
            value.model_call_result_fingerprint,
        )
        if self._result_locators.exists(locator.locator_fingerprint, "AGENT_MODEL_CALL_RESULT_INVALID"):
            existing = self._load_locator(self._result_locators, locator)
            if existing.target_fingerprint != value.model_call_result_fingerprint:
                raise OnlyAgentContextStoreError("AGENT_MODEL_CALL_RESULT_CONFLICT", value.model_call_plan_fingerprint)
        outcome = self._results.commit(
            value.model_call_result_fingerprint,
            value,
            OnlyAgentModelCallResultV1.from_dict,
            "AGENT_MODEL_CALL_RESULT_INVALID",
            "AGENT_MODEL_CALL_RESULT_CONFLICT",
        )
        self._result_locators.commit(
            locator.locator_fingerprint,
            locator,
            _OccurrenceLocatorV1.from_dict,
            "AGENT_MODEL_CALL_RESULT_INVALID",
            "AGENT_MODEL_CALL_RESULT_CONFLICT",
        )
        return outcome

    def load_result_for_plan_verified(self, plan_fingerprint: str) -> OnlyAgentModelCallResultV1:
        locator = self._load_locator_for(
            self._result_locators,
            _OccurrenceLocatorKind.MODEL_RESULT_BY_PLAN,
            plan_fingerprint,
            None,
            "AGENT_MODEL_CALL_RESULT_INVALID",
        )
        result = self._results.load(
            locator.target_fingerprint,
            OnlyAgentModelCallResultV1.from_dict,
            "AGENT_MODEL_CALL_RESULT_INVALID",
            "AGENT_MODEL_CALL_RESULT_CONFLICT",
        )
        if result.model_call_plan_fingerprint != plan_fingerprint:
            raise OnlyAgentContextStoreError("AGENT_MODEL_CALL_RESULT_CONFLICT", plan_fingerprint)
        return result

    def load_result_verified(self, result_fingerprint: str) -> OnlyAgentModelCallResultV1:
        return self._results.load(
            result_fingerprint,
            OnlyAgentModelCallResultV1.from_dict,
            "AGENT_MODEL_CALL_RESULT_INVALID",
            "AGENT_MODEL_CALL_RESULT_CONFLICT",
        )

    def result_exists(self, plan_fingerprint: str) -> bool:
        key = _OccurrenceLocatorV1.expected_fingerprint(
            _OccurrenceLocatorKind.MODEL_RESULT_BY_PLAN, plan_fingerprint, None
        )
        return self._result_locators.exists(key, "AGENT_MODEL_CALL_RESULT_INVALID")

    def budget_consumed(self, session_fingerprint: str) -> int:
        ordinal = 0
        while self._ordinal_locators.exists(
            _OccurrenceLocatorV1.expected_fingerprint(
                _OccurrenceLocatorKind.MODEL_PLAN_BY_SESSION_ORDINAL, session_fingerprint, ordinal
            ),
            "AGENT_OCCURRENCE_LOCATOR_MISSING",
        ):
            self.load_plan_by_session_ordinal_verified(session_fingerprint, ordinal)
            ordinal += 1
        return ordinal


class OnlyJsonAgentToolOccurrenceStore(_OccurrenceStoreHelpers):
    def __init__(self, semantic_root: object) -> None:
        from pathlib import Path

        if not isinstance(semantic_root, Path):
            raise TypeError("semantic_root must be a Path")
        self._plans = _OnlyJsonPutOnceStore(semantic_root, Path("research/agent-orchestration/tool-calls/plans"))
        self._results = _OnlyJsonPutOnceStore(semantic_root, Path("research/agent-orchestration/tool-calls/results"))
        self._ordinal_locators = _OnlyJsonPutOnceStore(
            semantic_root, Path("research/agent-orchestration/tool-calls/by-session-ordinal")
        )
        self._result_locators = _OnlyJsonPutOnceStore(
            semantic_root, Path("research/agent-orchestration/tool-calls/result-by-plan")
        )

    def commit_plan(self, value: OnlyAgentToolCallPlanV1) -> OnlyAgentCommitOutcome:
        locator = _OccurrenceLocatorV1(
            _OccurrenceLocatorKind.TOOL_PLAN_BY_SESSION_ORDINAL,
            value.agent_session_fingerprint,
            value.tool_call_ordinal,
            value.tool_call_plan_fingerprint,
        )
        if self._ordinal_locators.exists(locator.locator_fingerprint, "AGENT_TOOL_CALL_PLAN_INVALID"):
            existing = self._load_locator(self._ordinal_locators, locator)
            if existing.target_fingerprint != value.tool_call_plan_fingerprint:
                raise OnlyAgentContextStoreError("AGENT_OCCURRENCE_ORDINAL_CONFLICT", locator.locator_fingerprint)
        elif value.tool_call_ordinal != self.budget_consumed(value.agent_session_fingerprint):
            raise OnlyAgentContextStoreError("AGENT_OCCURRENCE_ORDINAL_CONFLICT", locator.locator_fingerprint)
        outcome = self._plans.commit(
            value.tool_call_plan_fingerprint,
            value,
            OnlyAgentToolCallPlanV1.from_dict,
            "AGENT_TOOL_CALL_PLAN_INVALID",
            "AGENT_TOOL_CALL_PLAN_CONFLICT",
        )
        self._ordinal_locators.commit(
            locator.locator_fingerprint,
            locator,
            _OccurrenceLocatorV1.from_dict,
            "AGENT_TOOL_CALL_PLAN_INVALID",
            "AGENT_OCCURRENCE_ORDINAL_CONFLICT",
        )
        return outcome

    def load_plan_verified(self, fingerprint: str) -> OnlyAgentToolCallPlanV1:
        return self._plans.load(
            fingerprint,
            OnlyAgentToolCallPlanV1.from_dict,
            "AGENT_TOOL_CALL_PLAN_INVALID",
            "AGENT_TOOL_CALL_PLAN_CONFLICT",
        )

    def load_plan_by_session_ordinal_verified(self, session_fingerprint: str, ordinal: int) -> OnlyAgentToolCallPlanV1:
        locator = self._load_locator_for(
            self._ordinal_locators,
            _OccurrenceLocatorKind.TOOL_PLAN_BY_SESSION_ORDINAL,
            session_fingerprint,
            ordinal,
            "AGENT_TOOL_CALL_PLAN_INVALID",
        )
        plan = self.load_plan_verified(locator.target_fingerprint)
        if plan.agent_session_fingerprint != session_fingerprint or plan.tool_call_ordinal != ordinal:
            raise OnlyAgentContextStoreError("AGENT_TOOL_CALL_PLAN_CONFLICT", locator.locator_fingerprint)
        return plan

    def commit_result(self, value: OnlyAgentToolCallResultV1) -> OnlyAgentCommitOutcome:
        self.load_plan_verified(value.tool_call_plan_fingerprint)
        locator = _OccurrenceLocatorV1(
            _OccurrenceLocatorKind.TOOL_RESULT_BY_PLAN,
            value.tool_call_plan_fingerprint,
            None,
            value.tool_call_result_fingerprint,
        )
        if self._result_locators.exists(locator.locator_fingerprint, "AGENT_TOOL_CALL_RESULT_INVALID"):
            existing = self._load_locator(self._result_locators, locator)
            if existing.target_fingerprint != value.tool_call_result_fingerprint:
                raise OnlyAgentContextStoreError("AGENT_TOOL_CALL_RESULT_CONFLICT", value.tool_call_plan_fingerprint)
        outcome = self._results.commit(
            value.tool_call_result_fingerprint,
            value,
            OnlyAgentToolCallResultV1.from_dict,
            "AGENT_TOOL_CALL_RESULT_INVALID",
            "AGENT_TOOL_CALL_RESULT_CONFLICT",
        )
        self._result_locators.commit(
            locator.locator_fingerprint,
            locator,
            _OccurrenceLocatorV1.from_dict,
            "AGENT_TOOL_CALL_RESULT_INVALID",
            "AGENT_TOOL_CALL_RESULT_CONFLICT",
        )
        return outcome

    def load_result_for_plan_verified(self, plan_fingerprint: str) -> OnlyAgentToolCallResultV1:
        locator = self._load_locator_for(
            self._result_locators,
            _OccurrenceLocatorKind.TOOL_RESULT_BY_PLAN,
            plan_fingerprint,
            None,
            "AGENT_TOOL_CALL_RESULT_INVALID",
        )
        result = self._results.load(
            locator.target_fingerprint,
            OnlyAgentToolCallResultV1.from_dict,
            "AGENT_TOOL_CALL_RESULT_INVALID",
            "AGENT_TOOL_CALL_RESULT_CONFLICT",
        )
        if result.tool_call_plan_fingerprint != plan_fingerprint:
            raise OnlyAgentContextStoreError("AGENT_TOOL_CALL_RESULT_CONFLICT", plan_fingerprint)
        return result

    def load_result_verified(self, result_fingerprint: str) -> OnlyAgentToolCallResultV1:
        return self._results.load(
            result_fingerprint,
            OnlyAgentToolCallResultV1.from_dict,
            "AGENT_TOOL_CALL_RESULT_INVALID",
            "AGENT_TOOL_CALL_RESULT_CONFLICT",
        )

    def result_exists(self, plan_fingerprint: str) -> bool:
        key = _OccurrenceLocatorV1.expected_fingerprint(
            _OccurrenceLocatorKind.TOOL_RESULT_BY_PLAN, plan_fingerprint, None
        )
        return self._result_locators.exists(key, "AGENT_TOOL_CALL_RESULT_INVALID")

    def budget_consumed(self, session_fingerprint: str) -> int:
        ordinal = 0
        while self._ordinal_locators.exists(
            _OccurrenceLocatorV1.expected_fingerprint(
                _OccurrenceLocatorKind.TOOL_PLAN_BY_SESSION_ORDINAL, session_fingerprint, ordinal
            ),
            "AGENT_OCCURRENCE_LOCATOR_MISSING",
        ):
            self.load_plan_by_session_ordinal_verified(session_fingerprint, ordinal)
            ordinal += 1
        return ordinal


__all__ = ["OnlyJsonAgentModelOccurrenceStore", "OnlyJsonAgentToolOccurrenceStore"]
