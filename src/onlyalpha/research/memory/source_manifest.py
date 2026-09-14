"""Exact cross-source witness; a missing family is never an empty family."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.source_cut import OnlySourceClosedCutV1

MANDATORY_FAMILY_SET_VERSION = 1
MANDATORY_FAMILIES = (
    "AGENT_PROVENANCE",
    "PRODUCT_COMMAND_ADMISSION",
    "PRODUCT_COMMAND_RECEIPT",
    "QUALIFICATION_DECISION",
    "RESEARCH_ATTEMPT",
    "RESEARCH_FACTOR_PAIR_STATISTICS",
    "RESEARCH_RESULT",
    "RESEARCH_RUN",
    "RESEARCH_STATISTICS",
    "RESEARCH_SUMMARY_STATISTICS",
    "SEARCH_PROVENANCE",
)


class OnlyMemoryProjectionError(ValueError):
    """Stable fail-closed projection error."""


@dataclass(frozen=True, slots=True)
class OnlyMemorySourceCutRefV1:
    source_family: str
    source_schema_version: int
    enumeration_contract_version: int
    cut_fingerprint: str
    cut_boundary: str
    completeness_proof: str

    def __post_init__(self) -> None:
        if (
            not self.source_family
            or type(self.source_schema_version) is not int
            or self.source_schema_version < 1
            or type(self.enumeration_contract_version) is not int
            or self.enumeration_contract_version < 1
            or not self.cut_boundary
            or not self.completeness_proof
            or not isinstance(self.cut_fingerprint, str)
            or len(self.cut_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in self.cut_fingerprint)
        ):
            raise OnlyMemoryProjectionError("SOURCE_CUT_SCHEMA_UNSUPPORTED")

    @classmethod
    def from_cut(cls, cut: OnlySourceClosedCutV1) -> OnlyMemorySourceCutRefV1:
        return cls(
            cut.source_family,
            cut.source_schema_version,
            cut.enumeration_contract_version,
            cut.cut_fingerprint,
            cut.cut_boundary,
            cut.completeness_proof,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_family": self.source_family,
            "source_schema_version": self.source_schema_version,
            "enumeration_contract_version": self.enumeration_contract_version,
            "cut_fingerprint": self.cut_fingerprint,
            "cut_boundary": self.cut_boundary,
            "completeness_proof": self.completeness_proof,
        }


@dataclass(frozen=True, slots=True)
class OnlyExperimentMemorySourceCutManifestV1:
    cuts: tuple[OnlyMemorySourceCutRefV1, ...]
    schema_version: int = 1
    mandatory_family_set_version: int = MANDATORY_FAMILY_SET_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.mandatory_family_set_version != MANDATORY_FAMILY_SET_VERSION:
            raise OnlyMemoryProjectionError("PROJECTION_SCHEMA_UNSUPPORTED")
        if tuple(cut.source_family for cut in self.cuts) != MANDATORY_FAMILIES:
            raise OnlyMemoryProjectionError("SOURCE_CUT_MISSING")

    @classmethod
    def from_cuts(cls, cuts: Sequence[OnlySourceClosedCutV1]) -> OnlyExperimentMemorySourceCutManifestV1:
        return cls(
            tuple(sorted((OnlyMemorySourceCutRefV1.from_cut(cut) for cut in cuts), key=lambda c: c.source_family))
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mandatory_family_set_version": self.mandatory_family_set_version,
            "cuts": [cut.to_dict() for cut in self.cuts],
            "manifest_fingerprint": self.manifest_fingerprint,
        }

    @property
    def manifest_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "schema_version": self.schema_version,
                "mandatory_family_set_version": self.mandatory_family_set_version,
                "cuts": [cut.to_dict() for cut in self.cuts],
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyExperimentMemorySourceCutManifestV1:
        if set(payload) != {"schema_version", "mandatory_family_set_version", "cuts", "manifest_fingerprint"}:
            raise OnlyMemoryProjectionError("PROJECTION_CORRUPT")
        try:
            raw = payload["cuts"]
            if not isinstance(raw, list):
                raise ValueError("cuts")
            cuts = tuple(OnlyMemorySourceCutRefV1(**item) for item in raw)
            version = payload["schema_version"]
            family_version = payload["mandatory_family_set_version"]
            if type(version) is not int or type(family_version) is not int:
                raise ValueError("version")
            result = cls(cuts, version, family_version)
            if result.manifest_fingerprint != payload["manifest_fingerprint"]:
                raise ValueError("fingerprint")
            return result
        except (ValueError, TypeError, KeyError) as exc:
            raise OnlyMemoryProjectionError("PROJECTION_CORRUPT") from exc
