"""Canonical operational evidence for deterministic admission re-resolution."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json, only_canonical_payload
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolution

from .errors import OnlyResearchRunAdmissionError


@dataclass(frozen=True, slots=True)
class OnlyResearchAdmissionResolutionEvidence:
    """Immutable, strict data projection of the existing V1/V2 admission bytes.

    The schema versions are the historical fingerprint schemas, not a new
    evidence identity. No executable resolution object is retained.
    """

    _canonical_payload: str

    def __post_init__(self) -> None:
        try:
            payload = json.loads(self._canonical_payload)
            _validate(payload)
            if only_canonical_json(payload) != self._canonical_payload:
                raise ValueError("noncanonical admission evidence")
        except (TypeError, ValueError, KeyError) as exc:
            raise OnlyResearchRunAdmissionError(
                "Admission evidence is not a canonical supported projection",
                code="RESEARCH_ADMISSION_EVIDENCE_INVALID",
            ) from exc

    @property
    def specification_fingerprint(self) -> str:
        return cast(str, self.to_dict()["specification_fingerprint"])

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self._canonical_payload))

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchAdmissionResolutionEvidence:
        try:
            _validate(payload)
            return cls(only_canonical_json(payload))
        except (TypeError, ValueError, KeyError) as exc:
            raise OnlyResearchRunAdmissionError(
                "Admission evidence fields are invalid", code="RESEARCH_ADMISSION_EVIDENCE_INVALID"
            ) from exc

    @classmethod
    def from_resolution(
        cls, resolution: OnlyResearchSpecificationResolution
    ) -> OnlyResearchAdmissionResolutionEvidence:
        return cls.from_dict(cast(dict[str, object], only_canonical_payload(_resolution_payload(resolution))))


def only_research_admission_resolution_fingerprint(resolution: OnlyResearchSpecificationResolution) -> str:
    return OnlyResearchAdmissionResolutionEvidence.from_resolution(resolution).fingerprint


def _resolution_payload(resolution: OnlyResearchSpecificationResolution) -> dict[str, object]:
    if not isinstance(resolution, OnlyResearchSpecificationResolution):
        raise TypeError("admission evidence requires a Specification Resolution")
    scientific = resolution.workload.result_plan.schema_version == 2
    candidates: list[dict[str, object]] = [
        {
            "calculation_id": item.calculation_id,
            "assignment": item.assignment,
            "graph_fingerprint": item.graph_fingerprint,
            "calculation_fingerprint": item.calculation_fingerprint,
            "node_fingerprints": item.node_fingerprints,
            **({"candidate_fingerprint": item.candidate_fingerprint} if scientific else {}),
        }
        for item in resolution.candidates
    ]
    payload: dict[str, object] = {
        "schema_version": 2 if scientific else 1,
        "specification_fingerprint": resolution.specification_fingerprint,
        "candidates": candidates,
        "statistics_fingerprints": [item.statistics_fingerprint for item in resolution.statistics],
        "research_result_plan_fingerprint": resolution.workload.result_plan.fingerprint,
    }
    if scientific:
        payload["published_series"] = resolution.published_series
        payload["signals"] = resolution.signals
    return payload


def _object(value: object, fields: set[str] | None = None) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("evidence requires a data object")
    if fields is not None and set(value) != fields:
        raise ValueError("evidence fields differ")
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("evidence requires a data array")
    return value


def _sha(value: object, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("evidence fingerprint is invalid")


def _text(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("evidence name is invalid")


def _validate(value: object) -> None:
    payload = _object(value)
    version = payload.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("evidence schema version differs")
    scientific = version == 2
    _object(
        payload,
        {
            "schema_version",
            "specification_fingerprint",
            "candidates",
            "statistics_fingerprints",
            "research_result_plan_fingerprint",
        }
        | ({"published_series", "signals"} if scientific else set()),
    )
    _sha(payload["specification_fingerprint"])
    _sha(payload["research_result_plan_fingerprint"])
    for raw in _sequence(payload["candidates"]):
        item = _object(
            raw,
            {
                "calculation_id",
                "assignment",
                "graph_fingerprint",
                "calculation_fingerprint",
                "node_fingerprints",
            }
            | ({"candidate_fingerprint"} if scientific else set()),
        )
        _text(item["calculation_id"])
        for scalar in _object(item["assignment"]).values():
            if scalar is not None and type(scalar) not in (str, int, bool):
                raise ValueError("assignment must contain canonical scalars")
        for fingerprint in _object(item["node_fingerprints"]).values():
            _sha(fingerprint)
        _sha(item["graph_fingerprint"])
        _sha(item["calculation_fingerprint"])
        if scientific:
            _sha(item["candidate_fingerprint"], nullable=True)
    for fingerprint in _sequence(payload["statistics_fingerprints"]):
        _sha(fingerprint)
    if scientific:
        for name in ("published_series", "signals"):
            for raw in _sequence(payload[name]):
                item = _object(
                    raw,
                    {
                        "candidate_fingerprint",
                        "calculation_fingerprint",
                        "node_fingerprint",
                        "output_name",
                    }
                    | ({"role"} if name == "signals" else set()),
                )
                _sha(item["candidate_fingerprint"], nullable=name == "published_series")
                _sha(item["calculation_fingerprint"])
                _sha(item["node_fingerprint"])
                _text(item["output_name"])
                if name == "signals" and item["role"] not in ("ELIGIBILITY", "ENTRY_SIGNAL", "EXIT_SIGNAL"):
                    raise ValueError("signal role is invalid")


__all__ = ["OnlyResearchAdmissionResolutionEvidence", "only_research_admission_resolution_fingerprint"]
