"""Operational identity and durable binding for externally retryable Product Commands."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from onlyalpha.canonical import only_canonical_fingerprint


@dataclass(frozen=True, order=True, slots=True)
class OnlyProductCommandId:
    value: str

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.value)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("Product Command ID must be a canonical UUID4") from exc
        if parsed.version != 4 or str(parsed) != self.value:
            raise ValueError("Product Command ID must be a canonical UUID4")

    def __str__(self) -> str:
        return self.value


class OnlyProductCommandKind(StrEnum):
    CREATE_RESEARCH_RUN = "CREATE_RESEARCH_RUN"
    CANCEL_RESEARCH_RUN = "CANCEL_RESEARCH_RUN"


class OnlyProductCommandOutcomeKind(StrEnum):
    RESEARCH_RUN = "RESEARCH_RUN"


@dataclass(frozen=True, slots=True)
class OnlyProductCommandOutcomeRef:
    kind: OnlyProductCommandOutcomeKind
    outcome_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, OnlyProductCommandOutcomeKind):
            raise ValueError("Product Command outcome kind is invalid")
        if self.kind is OnlyProductCommandOutcomeKind.RESEARCH_RUN:
            try:
                parsed = uuid.UUID(self.outcome_id)
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError("Research Run outcome ID must be a canonical UUID4") from exc
            if parsed.version != 4 or str(parsed) != self.outcome_id:
                raise ValueError("Research Run outcome ID must be a canonical UUID4")


@dataclass(frozen=True, slots=True)
class OnlyProductCommandReceipt:
    command_id: OnlyProductCommandId
    command_kind: OnlyProductCommandKind
    command_fingerprint: str
    outcome_ref: OnlyProductCommandOutcomeRef
    accepted_at: datetime
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, OnlyProductCommandId):
            raise ValueError("Product Command receipt ID is invalid")
        if not isinstance(self.command_kind, OnlyProductCommandKind):
            raise ValueError("Product Command receipt kind is invalid")
        if (
            not isinstance(self.command_fingerprint, str)
            or len(self.command_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in self.command_fingerprint)
        ):
            raise ValueError("Product Command fingerprint must be a lowercase SHA256")
        if not isinstance(self.outcome_ref, OnlyProductCommandOutcomeRef):
            raise ValueError("Product Command outcome reference is invalid")
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() != UTC.utcoffset(self.accepted_at):
            raise ValueError("Product Command accepted_at must be timezone-aware UTC")
        if self.schema_version != 1:
            raise ValueError("Product Command receipt schema version is unsupported")


def only_cancel_research_run_command_fingerprint(run_id: str) -> str:
    """Canonical operational intent identity for CancelResearchRun."""

    OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, run_id)
    return only_canonical_fingerprint({"run_id": run_id})


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
