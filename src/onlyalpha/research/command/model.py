"""Stable values and projections for the Research Command boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .errors import OnlyResearchRunCursorError

_SEARCH_EXPERIMENT_WORK_ID = re.compile(r"^search-experiment:[0-9a-f]{64}$")


def _authoring_generation(value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None):
        raise ValueError("Authoring Generation fingerprint is invalid")


@dataclass(frozen=True, slots=True)
class OnlyResearchSubmitCommand:
    submission_key: OnlyProductCommandId
    specification: OnlyResearchSpecification
    authoring_generation_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _authoring_generation(self.authoring_generation_fingerprint)

    @property
    def command_fingerprint(self) -> str:
        # The exact Generation reference is Product intent; provenance is derived evidence.
        payload: dict[str, object] = {"specification": self.specification.to_dict()}
        if self.authoring_generation_fingerprint is not None:
            payload["authoring_generation_fingerprint"] = self.authoring_generation_fingerprint
        return only_canonical_fingerprint(payload)


@dataclass(frozen=True, slots=True)
class OnlyDerivedResearchSubmitCommandV2:
    """Complete Product operational intent for Search-derived Research work."""

    submission_key: OnlyProductCommandId
    specification: OnlyResearchSpecification
    parent_runtime_work_id: str
    authoring_generation_fingerprint: str | None = None
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version != 2 or not isinstance(self.submission_key, OnlyProductCommandId):
            raise ValueError("Derived Research Submit command is invalid")
        if not isinstance(self.specification, OnlyResearchSpecification):
            raise ValueError("Derived Research specification is invalid")
        if (
            not isinstance(self.parent_runtime_work_id, str)
            or _SEARCH_EXPERIMENT_WORK_ID.fullmatch(self.parent_runtime_work_id) is None
        ):
            raise ValueError("Derived Research parent work identity is invalid")
        _authoring_generation(self.authoring_generation_fingerprint)

    @property
    def command_fingerprint(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "specification": self.specification.to_dict(),
            "parent_runtime_work_id": self.parent_runtime_work_id,
        }
        if self.authoring_generation_fingerprint is not None:
            payload["authoring_generation_fingerprint"] = self.authoring_generation_fingerprint
        return only_canonical_fingerprint(payload)


@dataclass(frozen=True, slots=True)
class OnlyNoveltyGatedResearchSubmitCommandV3:
    """Product intent for one Research action authorized by one exact Decision."""

    submission_key: OnlyProductCommandId
    specification: OnlyResearchSpecification
    novelty_decision_fingerprint: str
    parent_runtime_work_id: str | None = None
    authoring_generation_fingerprint: str | None = None
    schema_version: int = 3

    def __post_init__(self) -> None:
        if self.schema_version != 3 or not isinstance(self.submission_key, OnlyProductCommandId):
            raise ValueError("Novelty-gated Research Submit command is invalid")
        if not isinstance(self.specification, OnlyResearchSpecification):
            raise ValueError("Novelty-gated Research specification is invalid")
        if (
            not isinstance(self.novelty_decision_fingerprint, str)
            or len(self.novelty_decision_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in self.novelty_decision_fingerprint)
        ):
            raise ValueError("Novelty Decision fingerprint is invalid")
        if (
            self.parent_runtime_work_id is not None
            and _SEARCH_EXPERIMENT_WORK_ID.fullmatch(self.parent_runtime_work_id) is None
        ):
            raise ValueError("Novelty-gated Research parent work identity is invalid")
        _authoring_generation(self.authoring_generation_fingerprint)

    @property
    def command_fingerprint(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "specification": self.specification.to_dict(),
            "novelty_decision_fingerprint": self.novelty_decision_fingerprint,
            "parent_runtime_work_id": self.parent_runtime_work_id,
        }
        if self.authoring_generation_fingerprint is not None:
            payload["authoring_generation_fingerprint"] = self.authoring_generation_fingerprint
        return only_canonical_fingerprint(payload)


@dataclass(frozen=True, slots=True)
class OnlyNoveltyGatedResearchSubmitCommandV4:
    """Product intent for one Research action authorized by a complete Decision Group."""

    submission_key: OnlyProductCommandId
    specification: OnlyResearchSpecification
    novelty_decision_group_fingerprint: str
    parent_runtime_work_id: str | None = None
    authoring_generation_fingerprint: str | None = None
    schema_version: int = 4

    def __post_init__(self) -> None:
        if self.schema_version != 4 or not isinstance(self.submission_key, OnlyProductCommandId):
            raise ValueError("Novelty-gated Research Submit command is invalid")
        if not isinstance(self.specification, OnlyResearchSpecification):
            raise ValueError("Novelty-gated Research specification is invalid")
        if (
            not isinstance(self.novelty_decision_group_fingerprint, str)
            or len(self.novelty_decision_group_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in self.novelty_decision_group_fingerprint)
        ):
            raise ValueError("Novelty Decision Group fingerprint is invalid")
        if (
            self.parent_runtime_work_id is not None
            and _SEARCH_EXPERIMENT_WORK_ID.fullmatch(self.parent_runtime_work_id) is None
        ):
            raise ValueError("Novelty-gated Research parent work identity is invalid")
        _authoring_generation(self.authoring_generation_fingerprint)

    @property
    def command_fingerprint(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "specification": self.specification.to_dict(),
            "novelty_decision_group_fingerprint": self.novelty_decision_group_fingerprint,
            "parent_runtime_work_id": self.parent_runtime_work_id,
        }
        if self.authoring_generation_fingerprint is not None:
            payload["authoring_generation_fingerprint"] = self.authoring_generation_fingerprint
        return only_canonical_fingerprint(payload)


def only_derived_research_run_id(command_id: OnlyProductCommandId) -> OnlyResearchRunId:
    """Deterministically name one derived Run from its immutable Product identity."""

    if not isinstance(command_id, OnlyProductCommandId):
        raise ValueError("Derived Research Product Command ID is invalid")
    payload = b"ONLYALPHA_DERIVED_RESEARCH_RUN_ID_V1\x1f" + command_id.value.encode("ascii")
    raw = hashlib.sha256(payload).digest()[:16]
    return OnlyResearchRunId(str(uuid.UUID(bytes=raw, version=4)))


def only_novelty_gated_research_run_id(command_id: OnlyProductCommandId) -> OnlyResearchRunId:
    """Deterministically name V3 work for crash-safe cross-authority recovery."""

    if not isinstance(command_id, OnlyProductCommandId):
        raise ValueError("Novelty-gated Research Product Command ID is invalid")
    payload = b"ONLYALPHA_NOVELTY_GATED_RESEARCH_RUN_ID_V3\x1f" + command_id.value.encode("ascii")
    return OnlyResearchRunId(str(uuid.UUID(bytes=hashlib.sha256(payload).digest()[:16], version=4)))


def only_novelty_gated_research_run_id_v4(command_id: OnlyProductCommandId) -> OnlyResearchRunId:
    """Deterministically name V4 work for crash-safe cross-authority recovery."""

    if not isinstance(command_id, OnlyProductCommandId):
        raise ValueError("Novelty-gated Research Product Command ID is invalid")
    payload = b"ONLYALPHA_NOVELTY_GATED_RESEARCH_RUN_ID_V4\x1f" + command_id.value.encode("ascii")
    return OnlyResearchRunId(str(uuid.UUID(bytes=hashlib.sha256(payload).digest()[:16], version=4)))


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

    submission_key: OnlyProductCommandId
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
