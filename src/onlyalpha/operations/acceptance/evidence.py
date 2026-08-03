"""Canonical JSON conversion for acceptance evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from onlyalpha.domain.time import OnlyTimestamp

from .models import OnlyAcceptanceEvidence, OnlyAcceptanceVerdict
from .redaction import only_redact_acceptance_value


def only_acceptance_json_value(value: object) -> object:
    if isinstance(value, OnlyTimestamp):
        return value.to_datetime().isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(key): only_acceptance_json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [only_acceptance_json_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: only_acceptance_json_value(getattr(value, item.name)) for item in fields(value)}
    if hasattr(value, "to_dict"):
        return only_acceptance_json_value(value.to_dict())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported acceptance JSON value: {type(value).__name__}")


def only_evidence_to_dict(evidence: OnlyAcceptanceEvidence) -> dict[str, object]:
    payload = {
        "evidence_id": evidence.evidence_id,
        "case_id": evidence.case_id,
        "category": evidence.category,
        "verdict": evidence.verdict,
        "reason_code": evidence.reason_code,
        "started_at": evidence.started_at,
        "completed_at": evidence.completed_at,
        "expected": evidence.expected,
        "actual": evidence.actual,
        "artifact_paths": evidence.artifact_paths,
        "required": evidence.required,
    }
    return only_acceptance_json_value(only_redact_acceptance_value(payload))  # type: ignore[return-value]


def only_evidence_from_dict(payload: Mapping[str, object]) -> OnlyAcceptanceEvidence:
    return OnlyAcceptanceEvidence(
        evidence_id=str(payload["evidence_id"]),
        case_id=str(payload["case_id"]),
        category=str(payload["category"]),
        verdict=OnlyAcceptanceVerdict(str(payload["verdict"])),
        reason_code=str(payload["reason_code"]),
        started_at=OnlyTimestamp.from_datetime(
            datetime.fromisoformat(str(payload["started_at"]).replace("Z", "+00:00"))
        ),
        completed_at=OnlyTimestamp.from_datetime(
            datetime.fromisoformat(str(payload["completed_at"]).replace("Z", "+00:00"))
        ),
        expected=_mapping(payload.get("expected", {})),
        actual=_mapping(payload.get("actual", {})),
        artifact_paths=tuple(str(item) for item in _sequence(payload.get("artifact_paths", []))),
        required=bool(payload.get("required", True)),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("acceptance evidence mapping field is invalid")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("acceptance evidence sequence field is invalid")
    return value
