"""Immutable semantic proof of one verified Candidate to Strategy Freeze."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.canonical import only_canonical_fingerprint


@dataclass(frozen=True, order=True, slots=True)
class OnlyStrategyFreezeRelation:
    strategy_fingerprint: str
    candidate_fingerprint: str
    research_result_fingerprint: str
    research_execution_evidence_fingerprints: tuple[str, ...]
    admission_evidence_fingerprint: str
    equivalence_evidence_fingerprints: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Strategy Freeze Relation schema")
        for name in (
            "strategy_fingerprint",
            "candidate_fingerprint",
            "research_result_fingerprint",
            "admission_evidence_fingerprint",
        ):
            _sha(getattr(self, name), name)
        for name, values in (
            ("research_execution_evidence_fingerprint", self.research_execution_evidence_fingerprints),
            ("equivalence_evidence_fingerprint", self.equivalence_evidence_fingerprints),
        ):
            if not values or values != tuple(sorted(set(values))):
                raise ValueError(f"{name}s must be canonical, non-empty and unique")
            for value in values:
                _sha(value, name)

    @property
    def relation_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.strategy.freeze-relation",
                **self.to_dict(include_fingerprint=False),
            }
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "strategy_fingerprint": self.strategy_fingerprint,
            "candidate_fingerprint": self.candidate_fingerprint,
            "research_result_fingerprint": self.research_result_fingerprint,
            "research_execution_evidence_fingerprints": list(self.research_execution_evidence_fingerprints),
            "admission_evidence_fingerprint": self.admission_evidence_fingerprint,
            "equivalence_evidence_fingerprints": list(self.equivalence_evidence_fingerprints),
        }
        if include_fingerprint:
            payload["relation_fingerprint"] = self.relation_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyStrategyFreezeRelation:
        expected = {
            "schema_version",
            "strategy_fingerprint",
            "candidate_fingerprint",
            "research_result_fingerprint",
            "research_execution_evidence_fingerprints",
            "admission_evidence_fingerprint",
            "equivalence_evidence_fingerprints",
            "relation_fingerprint",
        }
        if set(payload) != expected:
            raise ValueError("Strategy Freeze Relation fields are invalid")
        provenance = payload["research_execution_evidence_fingerprints"]
        equivalence = payload["equivalence_evidence_fingerprints"]
        if not isinstance(provenance, list) or not isinstance(equivalence, list):
            raise ValueError("Strategy Freeze Relation evidence references must be arrays")
        relation = cls(
            str(payload["strategy_fingerprint"]),
            str(payload["candidate_fingerprint"]),
            str(payload["research_result_fingerprint"]),
            tuple(str(item) for item in provenance),
            str(payload["admission_evidence_fingerprint"]),
            tuple(str(item) for item in equivalence),
            int(str(payload["schema_version"])),
        )
        if payload["relation_fingerprint"] != relation.relation_fingerprint:
            raise ValueError("Strategy Freeze Relation identity differs")
        return relation


def _sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


__all__ = ["OnlyStrategyFreezeRelation"]
