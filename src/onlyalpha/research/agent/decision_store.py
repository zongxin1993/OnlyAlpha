"""Put-once persistence for Agent Decisions and Agent-to-Search lineage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from onlyalpha.canonical import only_canonical_fingerprint

from .decision import OnlyAgentDecisionV1, OnlyAgentExperimentLaunchRecordV1
from .errors import OnlyAgentContextStoreError
from .store import OnlyAgentCommitOutcome, _OnlyJsonPutOnceStore


class _DecisionLocatorKind(StrEnum):
    DECISION_BY_SESSION_ORDINAL = "DECISION_BY_SESSION_ORDINAL"
    LAUNCH_BY_SESSION = "LAUNCH_BY_SESSION"


def _sha(value: object, context: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(item not in "0123456789abcdef" for item in value):
        raise ValueError(f"{context} must be a lower-case SHA256")
    return value


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


@dataclass(frozen=True, slots=True)
class _DecisionLocatorV1:
    locator_kind: _DecisionLocatorKind
    session_fingerprint: str
    ordinal: int | None
    target_fingerprint: str
    locator_fingerprint: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.locator_kind, _DecisionLocatorKind):
            raise ValueError("AGENT_DECISION_LOCATOR_INVALID")
        _sha(self.session_fingerprint, "session_fingerprint")
        _sha(self.target_fingerprint, "target_fingerprint")
        expects_ordinal = self.locator_kind is _DecisionLocatorKind.DECISION_BY_SESSION_ORDINAL
        if expects_ordinal != (self.ordinal is not None) or (self.ordinal is not None and self.ordinal < 0):
            raise ValueError("AGENT_DECISION_LOCATOR_INVALID")
        expected = self.expected_fingerprint(self.locator_kind, self.session_fingerprint, self.ordinal)
        if not self.locator_fingerprint:
            object.__setattr__(self, "locator_fingerprint", expected)
        elif self.locator_fingerprint != expected:
            raise ValueError("AGENT_DECISION_LOCATOR_INVALID")

    @staticmethod
    def expected_fingerprint(kind: _DecisionLocatorKind, session: str, ordinal: int | None) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.agent-decision-locator",
                "schema_version": 1,
                "locator_kind": kind.value,
                "session_fingerprint": session,
                "ordinal": ordinal,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "locator_kind": self.locator_kind.value,
            "session_fingerprint": self.session_fingerprint,
            "ordinal": self.ordinal,
            "target_fingerprint": self.target_fingerprint,
            "locator_fingerprint": self.locator_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> _DecisionLocatorV1:
        if set(payload) != {
            "schema_version",
            "locator_kind",
            "session_fingerprint",
            "ordinal",
            "target_fingerprint",
            "locator_fingerprint",
        }:
            raise ValueError("AGENT_DECISION_LOCATOR_INVALID")
        ordinal = payload["ordinal"]
        return cls(
            _DecisionLocatorKind(str(payload["locator_kind"])),
            _sha(payload["session_fingerprint"], "session_fingerprint"),
            None if ordinal is None else _integer(ordinal, "ordinal"),
            _sha(payload["target_fingerprint"], "target_fingerprint"),
            _sha(payload["locator_fingerprint"], "locator_fingerprint"),
            _integer(payload["schema_version"], "schema_version"),
        )


class OnlyJsonAgentDecisionStore:
    def __init__(self, semantic_root: Path) -> None:
        self._decisions = _OnlyJsonPutOnceStore(semantic_root, Path("research/agent-orchestration/decisions"))
        self._locators = _OnlyJsonPutOnceStore(
            semantic_root, Path("research/agent-orchestration/decisions/by-session-ordinal")
        )
        self._coordination = _OnlyJsonPutOnceStore(
            semantic_root, Path("research/agent-orchestration/decisions/publication-locks")
        )

    def commit_decision(self, value: OnlyAgentDecisionV1) -> OnlyAgentCommitOutcome:
        locator = _DecisionLocatorV1(
            _DecisionLocatorKind.DECISION_BY_SESSION_ORDINAL,
            value.agent_session_fingerprint,
            value.decision_ordinal,
            value.decision_fingerprint,
        )
        with self._coordination.coordination_lock(locator.locator_fingerprint, "AGENT_DECISION_INVALID"):
            if self._locators.exists(locator.locator_fingerprint, "AGENT_DECISION_INVALID"):
                existing = self._load_locator(locator)
                if existing.target_fingerprint != value.decision_fingerprint:
                    raise OnlyAgentContextStoreError("AGENT_DECISION_ORDINAL_CONFLICT", locator.locator_fingerprint)
            elif value.decision_ordinal != self.contiguous_count(value.agent_session_fingerprint):
                raise OnlyAgentContextStoreError("AGENT_DECISION_ORDINAL_CONFLICT", locator.locator_fingerprint)
            outcome = self._decisions.commit(
                value.decision_fingerprint,
                value,
                OnlyAgentDecisionV1.from_dict,
                "AGENT_DECISION_INVALID",
                "AGENT_DECISION_CONFLICT",
            )
            self._locators.commit(
                locator.locator_fingerprint,
                locator,
                _DecisionLocatorV1.from_dict,
                "AGENT_DECISION_INVALID",
                "AGENT_DECISION_ORDINAL_CONFLICT",
            )
            return outcome

    def load_decision_verified(self, decision_fingerprint: str) -> OnlyAgentDecisionV1:
        return self._decisions.load(
            decision_fingerprint,
            OnlyAgentDecisionV1.from_dict,
            "AGENT_DECISION_INVALID",
            "AGENT_DECISION_CONFLICT",
        )

    def load_decision_by_session_ordinal_verified(self, session_fingerprint: str, ordinal: int) -> OnlyAgentDecisionV1:
        expected = _DecisionLocatorV1(
            _DecisionLocatorKind.DECISION_BY_SESSION_ORDINAL,
            session_fingerprint,
            ordinal,
            "0" * 64,
        )
        locator = self._load_locator(expected)
        value = self.load_decision_verified(locator.target_fingerprint)
        if value.agent_session_fingerprint != session_fingerprint or value.decision_ordinal != ordinal:
            raise OnlyAgentContextStoreError("AGENT_DECISION_CONFLICT", locator.locator_fingerprint)
        return value

    def decision_exists(self, session_fingerprint: str, ordinal: int) -> bool:
        key = _DecisionLocatorV1.expected_fingerprint(
            _DecisionLocatorKind.DECISION_BY_SESSION_ORDINAL, session_fingerprint, ordinal
        )
        return self._locators.exists(key, "AGENT_DECISION_INVALID")

    def contiguous_count(self, session_fingerprint: str) -> int:
        ordinal = 0
        while self.decision_exists(session_fingerprint, ordinal):
            self.load_decision_by_session_ordinal_verified(session_fingerprint, ordinal)
            ordinal += 1
        return ordinal

    def _load_locator(self, expected: _DecisionLocatorV1) -> _DecisionLocatorV1:
        key = _DecisionLocatorV1.expected_fingerprint(
            expected.locator_kind, expected.session_fingerprint, expected.ordinal
        )
        value = self._locators.load(
            key,
            _DecisionLocatorV1.from_dict,
            "AGENT_DECISION_INVALID",
            "AGENT_DECISION_ORDINAL_CONFLICT",
        )
        if (
            value.locator_kind is not expected.locator_kind
            or value.session_fingerprint != expected.session_fingerprint
            or value.ordinal != expected.ordinal
        ):
            raise OnlyAgentContextStoreError("AGENT_DECISION_ORDINAL_CONFLICT", key)
        return value


class OnlyJsonAgentExperimentLaunchStore:
    def __init__(self, semantic_root: Path) -> None:
        self._launches = _OnlyJsonPutOnceStore(semantic_root, Path("research/agent-orchestration/launch-records"))
        self._locators = _OnlyJsonPutOnceStore(
            semantic_root, Path("research/agent-orchestration/launch-records/by-session")
        )
        self._coordination = _OnlyJsonPutOnceStore(
            semantic_root, Path("research/agent-orchestration/launch-records/publication-locks")
        )

    def commit_launch_record(self, value: OnlyAgentExperimentLaunchRecordV1) -> OnlyAgentCommitOutcome:
        locator = _DecisionLocatorV1(
            _DecisionLocatorKind.LAUNCH_BY_SESSION,
            value.agent_session_fingerprint,
            None,
            value.experiment_launch_record_fingerprint,
        )
        key = locator.locator_fingerprint
        with self._coordination.coordination_lock(key, "AGENT_EXPERIMENT_LAUNCH_INVALID"):
            if self._locators.exists(key, "AGENT_EXPERIMENT_LAUNCH_INVALID"):
                existing = self._locators.load(
                    key,
                    _DecisionLocatorV1.from_dict,
                    "AGENT_EXPERIMENT_LAUNCH_INVALID",
                    "AGENT_EXPERIMENT_LAUNCH_CONFLICT",
                )
                if existing.target_fingerprint != value.experiment_launch_record_fingerprint:
                    raise OnlyAgentContextStoreError("AGENT_EXPERIMENT_LAUNCH_CONFLICT", key)
            outcome = self._launches.commit(
                value.experiment_launch_record_fingerprint,
                value,
                OnlyAgentExperimentLaunchRecordV1.from_dict,
                "AGENT_EXPERIMENT_LAUNCH_INVALID",
                "AGENT_EXPERIMENT_LAUNCH_CONFLICT",
            )
            self._locators.commit(
                key,
                locator,
                _DecisionLocatorV1.from_dict,
                "AGENT_EXPERIMENT_LAUNCH_INVALID",
                "AGENT_EXPERIMENT_LAUNCH_CONFLICT",
            )
            return outcome

    def load_launch_record_verified(self, fingerprint: str) -> OnlyAgentExperimentLaunchRecordV1:
        return self._launches.load(
            fingerprint,
            OnlyAgentExperimentLaunchRecordV1.from_dict,
            "AGENT_EXPERIMENT_LAUNCH_INVALID",
            "AGENT_EXPERIMENT_LAUNCH_CONFLICT",
        )

    def load_launch_record_by_session_verified(self, session_fingerprint: str) -> OnlyAgentExperimentLaunchRecordV1:
        key = _DecisionLocatorV1.expected_fingerprint(_DecisionLocatorKind.LAUNCH_BY_SESSION, session_fingerprint, None)
        locator = self._locators.load(
            key,
            _DecisionLocatorV1.from_dict,
            "AGENT_EXPERIMENT_LAUNCH_INVALID",
            "AGENT_EXPERIMENT_LAUNCH_CONFLICT",
        )
        value = self.load_launch_record_verified(locator.target_fingerprint)
        if value.agent_session_fingerprint != session_fingerprint:
            raise OnlyAgentContextStoreError("AGENT_EXPERIMENT_LAUNCH_CONFLICT", key)
        return value

    def launch_exists(self, session_fingerprint: str) -> bool:
        key = _DecisionLocatorV1.expected_fingerprint(_DecisionLocatorKind.LAUNCH_BY_SESSION, session_fingerprint, None)
        return self._locators.exists(key, "AGENT_EXPERIMENT_LAUNCH_INVALID")


__all__ = ["OnlyJsonAgentDecisionStore", "OnlyJsonAgentExperimentLaunchStore"]
