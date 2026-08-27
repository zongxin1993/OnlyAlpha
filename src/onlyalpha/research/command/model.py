"""Stable values and projections for the Research Command boundary."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .errors import OnlyResearchRunCursorError

OnlyResearchSubmissionKey = OnlyProductCommandId


@dataclass(frozen=True, slots=True)
class OnlyResearchSubmitCommand:
    submission_key: OnlyResearchSubmissionKey
    specification: OnlyResearchSpecification

    @property
    def command_fingerprint(self) -> str:
        return only_canonical_fingerprint({"specification": self.specification.to_dict()})


class OnlyResearchSubmitDisposition(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True)
class OnlyResearchSubmitOutcome:
    disposition: OnlyResearchSubmitDisposition
    run: OnlyResearchRun


@dataclass(frozen=True, slots=True)
class OnlyResearchSubmissionRecord:
    """Compatibility projection; Product Command Receipt is the sole durable authority."""

    submission_key: OnlyResearchSubmissionKey
    command_fingerprint: str
    run_id: OnlyResearchRunId

    def __post_init__(self) -> None:
        if (
            not isinstance(self.submission_key, OnlyProductCommandId)
            or not isinstance(self.command_fingerprint, str)
            or len(self.command_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in self.command_fingerprint)
            or not isinstance(self.run_id, OnlyResearchRunId)
        ):
            raise ValueError("Research submission record is invalid")


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("cursor timestamp must be timezone-aware UTC")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchRunPageCursor:
    queued_at: datetime
    run_id: OnlyResearchRunId

    def encode(self) -> str:
        payload = only_canonical_json({"queued_at": _timestamp(self.queued_at), "run_id": self.run_id.value, "v": 1})
        return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> OnlyResearchRunPageCursor:
        try:
            if not isinstance(value, str) or not value or "=" in value:
                raise ValueError("cursor must be unpadded base64url")
            raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
            payload = json.loads(raw)
            if not isinstance(payload, dict) or set(payload) != {"queued_at", "run_id", "v"} or payload["v"] != 1:
                raise ValueError("cursor payload is invalid")
            timestamp = datetime.fromisoformat(cast(str, payload["queued_at"]).replace("Z", "+00:00"))
            result = cls(timestamp, OnlyResearchRunId(cast(str, payload["run_id"])))
            if result.encode() != value or _timestamp(timestamp) != payload["queued_at"]:
                raise ValueError("cursor is not canonical")
            return result
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OnlyResearchRunCursorError() from exc


@dataclass(frozen=True, slots=True)
class OnlyResearchRunPage:
    runs: tuple[OnlyResearchRun, ...]
    has_more: bool
    next_cursor: str | None


__all__ = [name for name in globals() if name.startswith("Only")]
