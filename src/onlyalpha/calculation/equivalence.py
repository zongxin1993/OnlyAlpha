"""Admission-grade RESEARCH/TRADING Calculation equivalence evidence V2."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from onlyalpha.calculation.definition import (
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationTypeReference,
    OnlyFactorKind,
)
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json


class OnlyCalculationEquivalenceError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


class OnlyCalculationEquivalenceVerdict(StrEnum):
    EQUIVALENT = "EQUIVALENT"


@dataclass(frozen=True, slots=True)
class OnlyCalculationEquivalenceCertificationProfile:
    profile_id: str
    cases: tuple[str, ...]
    comparison_contract: str = "EXACT_TYPED_ORDERED_ROWS_V1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.profile_id.strip() or not self.comparison_contract.strip():
            raise ValueError("Equivalence Certification Profile contract is invalid")
        if not self.cases or self.cases != tuple(sorted(set(self.cases))):
            raise ValueError("Equivalence Certification Profile cases must be canonical and non-empty")

    @property
    def profile_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.calculation.equivalence-certification-profile",
                "schema_version": self.schema_version,
                "profile_id": self.profile_id,
                "cases": list(self.cases),
                "comparison_contract": self.comparison_contract,
            }
        )


@dataclass(frozen=True, slots=True)
class OnlyCalculationEquivalenceEvidenceV2:
    calculation_node_fingerprint: str
    calculation_type_reference: OnlyCalculationTypeReference
    research_implementation_fingerprint: str
    trading_implementation_fingerprint: str
    equivalence_contract_version: str
    certification_profile_id: str
    certification_profile_fingerprint: str
    corpus_fingerprint: str
    research_output_fingerprint: str
    trading_output_fingerprint: str
    comparison_fingerprint: str
    verdict: OnlyCalculationEquivalenceVerdict = OnlyCalculationEquivalenceVerdict.EQUIVALENT
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version != 2 or not self.equivalence_contract_version.strip():
            raise ValueError("Equivalence Evidence V2 contract is invalid")
        if not self.certification_profile_id.strip():
            raise ValueError("Equivalence Certification Profile ID is required")
        for name in (
            "calculation_node_fingerprint",
            "research_implementation_fingerprint",
            "trading_implementation_fingerprint",
            "certification_profile_fingerprint",
            "corpus_fingerprint",
            "research_output_fingerprint",
            "trading_output_fingerprint",
            "comparison_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if self.research_output_fingerprint != self.trading_output_fingerprint:
            raise ValueError("non-equivalent output identities cannot be published")
        if self.verdict is not OnlyCalculationEquivalenceVerdict.EQUIVALENT:
            raise ValueError("only EQUIVALENT Evidence V2 may be published")
        if self.comparison_fingerprint != only_calculation_equivalence_comparison_fingerprint(
            calculation_node_fingerprint=self.calculation_node_fingerprint,
            research_implementation_fingerprint=self.research_implementation_fingerprint,
            trading_implementation_fingerprint=self.trading_implementation_fingerprint,
            equivalence_contract_version=self.equivalence_contract_version,
            certification_profile_fingerprint=self.certification_profile_fingerprint,
            corpus_fingerprint=self.corpus_fingerprint,
            research_output_fingerprint=self.research_output_fingerprint,
            trading_output_fingerprint=self.trading_output_fingerprint,
        ):
            raise ValueError("Equivalence comparison identity differs")

    @property
    def evidence_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.calculation.equivalence-evidence",
                **self.to_dict(include_fingerprint=False),
            }
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        reference = self.calculation_type_reference
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "calculation_node_fingerprint": self.calculation_node_fingerprint,
            "calculation_type_reference": {
                "kind": reference.kind.value,
                "type_id": reference.type_id,
                "semantic_version": reference.semantic_version,
            },
            "research_implementation_fingerprint": self.research_implementation_fingerprint,
            "trading_implementation_fingerprint": self.trading_implementation_fingerprint,
            "equivalence_contract_version": self.equivalence_contract_version,
            "certification_profile_id": self.certification_profile_id,
            "certification_profile_fingerprint": self.certification_profile_fingerprint,
            "corpus_fingerprint": self.corpus_fingerprint,
            "research_output_fingerprint": self.research_output_fingerprint,
            "trading_output_fingerprint": self.trading_output_fingerprint,
            "comparison_fingerprint": self.comparison_fingerprint,
            "verdict": self.verdict.value,
        }
        if include_fingerprint:
            payload["evidence_fingerprint"] = self.evidence_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyCalculationEquivalenceEvidenceV2:
        expected = {
            "schema_version",
            "calculation_node_fingerprint",
            "calculation_type_reference",
            "research_implementation_fingerprint",
            "trading_implementation_fingerprint",
            "equivalence_contract_version",
            "certification_profile_id",
            "certification_profile_fingerprint",
            "corpus_fingerprint",
            "research_output_fingerprint",
            "trading_output_fingerprint",
            "comparison_fingerprint",
            "verdict",
            "evidence_fingerprint",
        }
        reference = payload.get("calculation_type_reference")
        if set(payload) != expected or not isinstance(reference, Mapping):
            raise ValueError("Equivalence Evidence V2 fields are invalid")
        if set(reference) != {"kind", "type_id", "semantic_version"}:
            raise ValueError("Equivalence Evidence V2 Calculation reference is invalid")
        from onlyalpha.calculation.definition import OnlyCalculationKind

        evidence = cls(
            _string(payload, "calculation_node_fingerprint"),
            OnlyCalculationTypeReference(
                OnlyCalculationKind(_string(reference, "kind")),
                _string(reference, "type_id"),
                _string(reference, "semantic_version"),
            ),
            _string(payload, "research_implementation_fingerprint"),
            _string(payload, "trading_implementation_fingerprint"),
            _string(payload, "equivalence_contract_version"),
            _string(payload, "certification_profile_id"),
            _string(payload, "certification_profile_fingerprint"),
            _string(payload, "corpus_fingerprint"),
            _string(payload, "research_output_fingerprint"),
            _string(payload, "trading_output_fingerprint"),
            _string(payload, "comparison_fingerprint"),
            OnlyCalculationEquivalenceVerdict(_string(payload, "verdict")),
            _integer(payload, "schema_version"),
        )
        if payload["evidence_fingerprint"] != evidence.evidence_fingerprint:
            raise ValueError("Equivalence Evidence V2 identity differs")
        return evidence


@dataclass(frozen=True, slots=True)
class _OnlyCertifiedCalculationEquivalenceEvidenceV2:
    evidence: OnlyCalculationEquivalenceEvidenceV2
    seal: object


_CERTIFICATION_SEAL = object()


def _only_seal_certified_equivalence(
    evidence: OnlyCalculationEquivalenceEvidenceV2,
) -> _OnlyCertifiedCalculationEquivalenceEvidenceV2:
    return _OnlyCertifiedCalculationEquivalenceEvidenceV2(evidence, _CERTIFICATION_SEAL)


class OnlyCalculationEquivalenceEvidenceV2Store:
    def __init__(self, semantic_root: Path) -> None:
        self._root = semantic_root / "calculation-equivalence" / "evidence-v2" / "sha256"

    def exists(self, evidence_fingerprint: str) -> bool:
        return self._target(_fingerprint(evidence_fingerprint)).is_dir()

    def publish_certified(
        self, certified: _OnlyCertifiedCalculationEquivalenceEvidenceV2
    ) -> OnlyCalculationEquivalenceEvidenceV2:
        if (
            not isinstance(certified, _OnlyCertifiedCalculationEquivalenceEvidenceV2)
            or certified.seal is not _CERTIFICATION_SEAL
        ):
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_CERTIFICATION_FAILED", "publication requires official Certification Authority"
            )
        evidence = certified.evidence
        fingerprint = evidence.evidence_fingerprint
        target = self._target(fingerprint)
        if target.exists() or target.is_symlink():
            existing = self.load_verified(fingerprint)
            if existing != evidence:
                raise OnlyCalculationEquivalenceError("DETERMINISTIC_EQUIVALENCE_CONFLICT", fingerprint)
            return existing
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            manifest = stage / "manifest.json"
            with manifest.open("x", encoding="utf-8") as stream:
                stream.write(only_canonical_json(evidence.to_dict()))
                stream.flush()
                os.fsync(stream.fileno())
            self._read_verified(stage, fingerprint)
            directory = os.open(stage, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            os.rename(stage, target)
            parent = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            return self.load_verified(fingerprint)
        except OnlyCalculationEquivalenceError:
            raise
        except OSError as exc:
            if target.is_dir():
                existing = self.load_verified(fingerprint)
                if existing == evidence:
                    return existing
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_COMMIT_FAILED", fingerprint) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load_verified(self, evidence_fingerprint: str) -> OnlyCalculationEquivalenceEvidenceV2:
        fingerprint = _fingerprint(evidence_fingerprint)
        return self._read_verified(self._target(fingerprint), fingerprint)

    def require_verified(
        self,
        *,
        calculation_node_fingerprint: str,
        reference: OnlyCalculationTypeReference,
        research_implementation_fingerprint: str,
        trading_implementation_fingerprint: str,
        certification_profile_fingerprint: str,
    ) -> OnlyCalculationEquivalenceEvidenceV2:
        for value in (
            calculation_node_fingerprint,
            research_implementation_fingerprint,
            trading_implementation_fingerprint,
            certification_profile_fingerprint,
        ):
            _fingerprint(value)
        if not self._root.exists():
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_NOT_FOUND", calculation_node_fingerprint)
        if not self._root.is_dir() or self._root.is_symlink():
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_CORRUPT", "authority root")
        matches: list[OnlyCalculationEquivalenceEvidenceV2] = []
        try:
            for prefix in sorted(self._root.iterdir(), key=lambda item: item.name):
                if prefix.is_symlink() or not prefix.is_dir() or len(prefix.name) != 2:
                    raise ValueError("unexpected Evidence V2 prefix")
                for target in sorted(prefix.iterdir(), key=lambda item: item.name):
                    evidence = self.load_verified(target.name)
                    if (
                        evidence.calculation_node_fingerprint == calculation_node_fingerprint
                        and evidence.calculation_type_reference == reference
                        and evidence.research_implementation_fingerprint == research_implementation_fingerprint
                        and evidence.trading_implementation_fingerprint == trading_implementation_fingerprint
                        and evidence.certification_profile_fingerprint == certification_profile_fingerprint
                    ):
                        matches.append(evidence)
        except OnlyCalculationEquivalenceError:
            raise
        except Exception as exc:
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_CORRUPT", "authority scan") from exc
        if len(matches) != 1:
            code = "EQUIVALENCE_EVIDENCE_NOT_FOUND" if not matches else "EQUIVALENCE_EVIDENCE_CORRUPT"
            raise OnlyCalculationEquivalenceError(code, calculation_node_fingerprint)
        return matches[0]

    def _read_verified(self, root: Path, expected: str) -> OnlyCalculationEquivalenceEvidenceV2:
        if not root.is_dir():
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_NOT_FOUND", expected)
        try:
            manifest = root / "manifest.json"
            if root.is_symlink() or manifest.is_symlink():
                raise ValueError("Equivalence Evidence V2 may not contain symlinks")
            if {item.name for item in root.iterdir()} != {"manifest.json"} or not manifest.is_file():
                raise ValueError("unexpected Equivalence Evidence V2 entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, Mapping):
                raise ValueError("Equivalence Evidence V2 manifest must be an object")
            evidence = OnlyCalculationEquivalenceEvidenceV2.from_dict(payload)
            if evidence.evidence_fingerprint != expected or raw != only_canonical_json(payload):
                raise ValueError("Equivalence Evidence V2 path/content identity differs")
            return evidence
        except OnlyCalculationEquivalenceError:
            raise
        except Exception as exc:
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_CORRUPT", expected) from exc

    def _target(self, fingerprint: str) -> Path:
        return self._root / fingerprint[:2] / fingerprint


def only_calculation_equivalence_comparison_fingerprint(
    *,
    calculation_node_fingerprint: str,
    research_implementation_fingerprint: str,
    trading_implementation_fingerprint: str,
    equivalence_contract_version: str,
    certification_profile_fingerprint: str,
    corpus_fingerprint: str,
    research_output_fingerprint: str,
    trading_output_fingerprint: str,
) -> str:
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.calculation.equivalence-comparison",
            "schema_version": 2,
            "calculation_node_fingerprint": calculation_node_fingerprint,
            "research_implementation_fingerprint": research_implementation_fingerprint,
            "trading_implementation_fingerprint": trading_implementation_fingerprint,
            "equivalence_contract_version": equivalence_contract_version,
            "certification_profile_fingerprint": certification_profile_fingerprint,
            "corpus_fingerprint": corpus_fingerprint,
            "research_output_fingerprint": research_output_fingerprint,
            "trading_output_fingerprint": trading_output_fingerprint,
            "comparison": "EXACT_TYPED_ORDERED_ROWS",
        }
    )


def only_required_calculation_equivalence_profile(
    definition: OnlyCalculationDefinition,
) -> OnlyCalculationEquivalenceCertificationProfile:
    """Resolve the closed P9.0 profile from exact node semantics."""

    if definition.factor_kind is OnlyFactorKind.CROSS_SECTION or definition.kind is OnlyCalculationKind.TARGET:
        raise OnlyCalculationEquivalenceError(
            "EQUIVALENCE_CERTIFICATION_PROFILE_UNAVAILABLE",
            f"{definition.type_id}@{definition.semantic_version}",
        )
    cases = {
        "FLAT_SEQUENCE",
        "NEGATIVE_SLOPE_SEQUENCE",
        "POSITIVE_SLOPE_SEQUENCE",
        "QUANTIZATION_BOUNDARY",
        "WARMUP_AND_STEADY_STATE",
        "ZERO_BOUNDARY",
    }
    if any(item.nullable for item in definition.inputs):
        cases.add("NULLABLE_INPUT_SEMANTICS")
    if any(item.data_type is OnlyCalculationDataType.BOOLEAN for item in definition.inputs):
        cases.add("BOOLEAN_TRUTH_NULL_SEMANTICS")
    if len(definition.outputs) > 1:
        cases.add("MULTI_OUTPUT_ALIGNMENT")
    return OnlyCalculationEquivalenceCertificationProfile(
        "ONLYALPHA_P9_CALCULATION_EQUIVALENCE_V2",
        tuple(sorted(cases)),
    )


def _fingerprint(value: str) -> str:
    try:
        _sha(value, "fingerprint")
    except ValueError as exc:
        raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_NOT_FOUND", "invalid fingerprint") from exc
    return value


def _sha(value: str, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
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


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
