"""Market-neutral deterministic submission controls for the Virtual Broker."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel


class OnlyVirtualSubmissionAction(StrEnum):
    """Explicit non-default actions selected by 1-based submission index."""

    REJECT_BEFORE_ACCEPTED = "REJECT_BEFORE_ACCEPTED"
    ACCEPT_THEN_EXPIRE = "ACCEPT_THEN_EXPIRE"


@dataclass(frozen=True, slots=True)
class OnlyVirtualSubmissionControl(OnlyDomainModel):
    submission_index: int
    action: OnlyVirtualSubmissionAction
    reason: str | None = None
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, OnlyVirtualSubmissionAction):
            raise ValueError("VIRTUAL_SUBMISSION_ACTION_INVALID")
        if isinstance(self.submission_index, bool) or self.submission_index < 1:
            raise ValueError("VIRTUAL_SUBMISSION_INDEX_INVALID")
        if self.reason is not None and (not isinstance(self.reason, str) or not self.reason.strip()):
            raise ValueError("VIRTUAL_SUBMISSION_REASON_INVALID")
        if self.rejection_code is not None and (
            not isinstance(self.rejection_code, str) or not self.rejection_code.strip()
        ):
            raise ValueError("VIRTUAL_SUBMISSION_REJECTION_CODE_INVALID")
        if self.action is OnlyVirtualSubmissionAction.ACCEPT_THEN_EXPIRE and self.rejection_code is not None:
            raise ValueError("VIRTUAL_SUBMISSION_REJECTION_CODE_NOT_APPLICABLE")

    @property
    def effective_reason(self) -> str:
        if self.reason is not None:
            return self.reason
        if self.action is OnlyVirtualSubmissionAction.REJECT_BEFORE_ACCEPTED:
            return "deterministic Virtual Broker rejection before acceptance"
        return "deterministic Virtual Broker expiry after acceptance"

    @property
    def effective_rejection_code(self) -> str | None:
        if self.action is not OnlyVirtualSubmissionAction.REJECT_BEFORE_ACCEPTED:
            return None
        return self.rejection_code or "VIRTUAL_SIMULATION_REJECTED"

    def canonical_payload(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "reason": self.effective_reason,
            "rejection_code": self.effective_rejection_code,
            "submission_index": self.submission_index,
        }


@dataclass(frozen=True, slots=True)
class OnlyVirtualSubmissionSimulation(OnlyDomainModel):
    submissions: tuple[OnlyVirtualSubmissionControl, ...] = ()

    def __post_init__(self) -> None:
        if not all(isinstance(item, OnlyVirtualSubmissionControl) for item in self.submissions):
            raise ValueError("VIRTUAL_SUBMISSION_CONTROL_INVALID")
        normalized = tuple(sorted(tuple(self.submissions), key=lambda item: item.submission_index))
        indexes = tuple(item.submission_index for item in normalized)
        if len(indexes) != len(set(indexes)):
            raise ValueError("VIRTUAL_SUBMISSION_INDEX_DUPLICATE")
        object.__setattr__(self, "submissions", normalized)

    def control_for(self, submission_index: int) -> OnlyVirtualSubmissionControl | None:
        if isinstance(submission_index, bool) or submission_index < 1:
            raise ValueError("VIRTUAL_SUBMISSION_INDEX_INVALID")
        return next(
            (item for item in self.submissions if item.submission_index == submission_index),
            None,
        )

    @property
    def fingerprint(self) -> str:
        payload = {
            "schema_version": 1,
            "submissions": [item.canonical_payload() for item in self.submissions],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def only_virtual_submission_control_to_checkpoint(
    control: OnlyVirtualSubmissionControl | None,
) -> object:
    return None if control is None else control.canonical_payload()


def only_virtual_submission_control_from_checkpoint(
    payload: object,
) -> OnlyVirtualSubmissionControl | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Virtual submission control checkpoint must be an object")
    expected = {"action", "reason", "rejection_code", "submission_index"}
    if set(payload) != expected:
        raise ValueError("VIRTUAL_SUBMISSION_CONTROL_CHECKPOINT_INVALID")
    raw_index = payload["submission_index"]
    raw_action = payload["action"]
    raw_reason = payload["reason"]
    raw_code = payload["rejection_code"]
    if (
        not isinstance(raw_index, int)
        or isinstance(raw_index, bool)
        or not isinstance(raw_action, str)
        or not isinstance(raw_reason, str)
        or (raw_code is not None and not isinstance(raw_code, str))
    ):
        raise ValueError("VIRTUAL_SUBMISSION_CONTROL_CHECKPOINT_INVALID")
    try:
        action = OnlyVirtualSubmissionAction(raw_action)
    except ValueError as exc:
        raise ValueError("VIRTUAL_SUBMISSION_ACTION_INVALID") from exc
    control = OnlyVirtualSubmissionControl(raw_index, action, raw_reason, raw_code)
    if control.canonical_payload() != payload:
        raise ValueError("VIRTUAL_SUBMISSION_CONTROL_CHECKPOINT_INVALID")
    return control


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
