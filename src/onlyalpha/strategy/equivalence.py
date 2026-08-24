"""Load-only legacy Equivalence Evidence V1 inspection boundary.

V1 is intentionally not an admission or publication authority. Admission-grade
evidence lives in ``onlyalpha.calculation.equivalence`` V2.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from onlyalpha.calculation.definition import OnlyCalculationKind, OnlyCalculationTypeReference
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.strategy.errors import OnlyCalculationEquivalenceError


class OnlyLegacyCalculationEquivalenceVerdictV1(StrEnum):
    EQUIVALENT = "EQUIVALENT"


@dataclass(frozen=True, slots=True)
class OnlyLegacyCalculationEquivalenceEvidenceV1:
    calculation_type_reference: OnlyCalculationTypeReference
    research_implementation_fingerprint: str
    trading_implementation_fingerprint: str
    equivalence_contract_version: str
    fixture_or_corpus_fingerprint: str
    research_output_fingerprint: str
    trading_output_fingerprint: str
    comparison_fingerprint: str
    verdict: OnlyLegacyCalculationEquivalenceVerdictV1 = OnlyLegacyCalculationEquivalenceVerdictV1.EQUIVALENT
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.equivalence_contract_version.strip():
            raise ValueError("legacy Equivalence Evidence V1 contract is invalid")
        for name in (
            "research_implementation_fingerprint",
            "trading_implementation_fingerprint",
            "fixture_or_corpus_fingerprint",
            "research_output_fingerprint",
            "trading_output_fingerprint",
            "comparison_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if self.verdict is not OnlyLegacyCalculationEquivalenceVerdictV1.EQUIVALENT:
            raise ValueError("legacy Equivalence Evidence V1 verdict is invalid")
        if self.research_output_fingerprint != self.trading_output_fingerprint:
            raise ValueError("legacy non-equivalent output identities are invalid")
        if self.comparison_fingerprint != _legacy_comparison_fingerprint(self):
            raise ValueError("legacy Equivalence comparison identity differs")

    @property
    def evidence_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        reference = self.calculation_type_reference
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "calculation_type_reference": {
                "kind": reference.kind.value,
                "type_id": reference.type_id,
                "semantic_version": reference.semantic_version,
            },
            "research_implementation_fingerprint": self.research_implementation_fingerprint,
            "trading_implementation_fingerprint": self.trading_implementation_fingerprint,
            "equivalence_contract_version": self.equivalence_contract_version,
            "fixture_or_corpus_fingerprint": self.fixture_or_corpus_fingerprint,
            "research_output_fingerprint": self.research_output_fingerprint,
            "trading_output_fingerprint": self.trading_output_fingerprint,
            "comparison_fingerprint": self.comparison_fingerprint,
            "verdict": self.verdict.value,
        }
        if include_fingerprint:
            payload["evidence_fingerprint"] = self.evidence_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyLegacyCalculationEquivalenceEvidenceV1:
        expected = {
            "schema_version",
            "calculation_type_reference",
            "research_implementation_fingerprint",
            "trading_implementation_fingerprint",
            "equivalence_contract_version",
            "fixture_or_corpus_fingerprint",
            "research_output_fingerprint",
            "trading_output_fingerprint",
            "comparison_fingerprint",
            "verdict",
            "evidence_fingerprint",
        }
        reference = payload.get("calculation_type_reference")
        if set(payload) != expected or not isinstance(reference, Mapping):
            raise ValueError("legacy Equivalence Evidence V1 fields are invalid")
        if set(reference) != {"kind", "type_id", "semantic_version"}:
            raise ValueError("legacy Calculation reference fields are invalid")
        evidence = cls(
            OnlyCalculationTypeReference(
                OnlyCalculationKind(_string(reference, "kind")),
                _string(reference, "type_id"),
                _string(reference, "semantic_version"),
            ),
            _string(payload, "research_implementation_fingerprint"),
            _string(payload, "trading_implementation_fingerprint"),
            _string(payload, "equivalence_contract_version"),
            _string(payload, "fixture_or_corpus_fingerprint"),
            _string(payload, "research_output_fingerprint"),
            _string(payload, "trading_output_fingerprint"),
            _string(payload, "comparison_fingerprint"),
            OnlyLegacyCalculationEquivalenceVerdictV1(_string(payload, "verdict")),
            _integer(payload, "schema_version"),
        )
        if payload["evidence_fingerprint"] != evidence.evidence_fingerprint:
            raise ValueError("legacy Equivalence Evidence V1 identity differs")
        return evidence


class OnlyLegacyCalculationEquivalenceEvidenceV1Reader:
    """Historical inspection only: no commit, scan, require, or upgrade capability."""

    def __init__(self, semantic_root: Path) -> None:
        self._root = semantic_root / "calculation-equivalence" / "evidence"

    def load_verified(self, evidence_fingerprint: str) -> OnlyLegacyCalculationEquivalenceEvidenceV1:
        _sha(evidence_fingerprint, "legacy Evidence V1 fingerprint")
        root = self._root / evidence_fingerprint[:2] / evidence_fingerprint
        if not root.is_dir():
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_NOT_FOUND", evidence_fingerprint)
        try:
            manifest = root / "manifest.json"
            if root.is_symlink() or manifest.is_symlink():
                raise ValueError("legacy Evidence V1 may not contain symlinks")
            if {item.name for item in root.iterdir()} != {"manifest.json"} or not manifest.is_file():
                raise ValueError("unexpected legacy Evidence V1 entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, Mapping):
                raise ValueError("legacy Evidence V1 manifest must be an object")
            evidence = OnlyLegacyCalculationEquivalenceEvidenceV1.from_dict(payload)
            if evidence.evidence_fingerprint != evidence_fingerprint or raw != only_canonical_json(payload):
                raise ValueError("legacy Evidence V1 path/content identity differs")
            return evidence
        except Exception as exc:
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_CORRUPT", evidence_fingerprint) from exc


def _legacy_comparison_fingerprint(evidence: OnlyLegacyCalculationEquivalenceEvidenceV1) -> str:
    reference = evidence.calculation_type_reference
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.calculation.equivalence-comparison",
            "schema_version": 1,
            "calculation_type_reference": {
                "kind": reference.kind.value,
                "type_id": reference.type_id,
                "semantic_version": reference.semantic_version,
            },
            "equivalence_contract_version": evidence.equivalence_contract_version,
            "fixture_or_corpus_fingerprint": evidence.fixture_or_corpus_fingerprint,
            "research_output_fingerprint": evidence.research_output_fingerprint,
            "trading_output_fingerprint": evidence.trading_output_fingerprint,
            "comparison": "EXACT_TYPED_ROWS",
        }
    )


def _sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _integer(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


__all__ = [name for name in globals() if name.startswith("OnlyLegacy")]
