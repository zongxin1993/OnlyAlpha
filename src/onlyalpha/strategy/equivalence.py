"""Verified immutable cross-backend Calculation equivalence evidence."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from onlyalpha.calculation.definition import OnlyCalculationBackendKind, OnlyCalculationTypeReference
from onlyalpha.calculation.implementation import OnlyCalculationImplementationManifest
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.strategy.errors import OnlyCalculationEquivalenceError


class OnlyCalculationEquivalenceVerdict(StrEnum):
    EQUIVALENT = "EQUIVALENT"


@dataclass(frozen=True, slots=True)
class OnlyCalculationEquivalenceCorpus:
    corpus_id: str
    semantic_payload: object
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.corpus_id.strip():
            raise ValueError("Equivalence corpus identity is invalid")
        _typed_value(self.semantic_payload)

    @property
    def corpus_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.calculation.equivalence-corpus",
                "schema_version": self.schema_version,
                "corpus_id": self.corpus_id,
                "semantic_payload": _typed_value(self.semantic_payload),
            }
        )


@dataclass(frozen=True, order=True, slots=True)
class OnlyCalculationEquivalenceRow:
    instrument_id: str
    timestamp_ns: int
    outputs: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("Equivalence row instrument is required")
        if not isinstance(self.timestamp_ns, int) or isinstance(self.timestamp_ns, bool):
            raise ValueError("Equivalence row timestamp must be an integer nanosecond")
        canonical = tuple(sorted(self.outputs, key=lambda item: item[0]))
        if not canonical or canonical != self.outputs or len({item[0] for item in canonical}) != len(canonical):
            raise ValueError("Equivalence row outputs must be canonical, non-empty and unique")
        for name, value in canonical:
            if not name.strip():
                raise ValueError("Equivalence output name is required")
            _typed_value(value)

    def semantic_payload(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "timestamp_ns": self.timestamp_ns,
            "outputs": {name: _typed_value(value) for name, value in self.outputs},
        }


@dataclass(frozen=True, slots=True)
class OnlyCalculationEquivalenceExecution:
    rows: tuple[OnlyCalculationEquivalenceRow, ...]

    def __post_init__(self) -> None:
        keys = tuple((item.instrument_id, item.timestamp_ns) for item in self.rows)
        if not keys or keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("Equivalence output axis must be non-empty, canonical and unique")

    @property
    def output_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.calculation.equivalence-output",
                "schema_version": 1,
                "rows": [item.semantic_payload() for item in self.rows],
            }
        )


class OnlyCalculationEquivalenceRunner(Protocol):
    def execute(
        self,
        reference: OnlyCalculationTypeReference,
        corpus: OnlyCalculationEquivalenceCorpus,
    ) -> OnlyCalculationEquivalenceExecution: ...


@dataclass(frozen=True, slots=True)
class OnlyCalculationEquivalenceEvidence:
    calculation_type_reference: OnlyCalculationTypeReference
    research_implementation_fingerprint: str
    trading_implementation_fingerprint: str
    equivalence_contract_version: str
    fixture_or_corpus_fingerprint: str
    research_output_fingerprint: str
    trading_output_fingerprint: str
    comparison_fingerprint: str
    verdict: OnlyCalculationEquivalenceVerdict = OnlyCalculationEquivalenceVerdict.EQUIVALENT
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.equivalence_contract_version.strip():
            raise ValueError("Equivalence Evidence contract is invalid")
        for name, value in (
            ("Research implementation", self.research_implementation_fingerprint),
            ("Trading implementation", self.trading_implementation_fingerprint),
            ("corpus", self.fixture_or_corpus_fingerprint),
            ("Research output", self.research_output_fingerprint),
            ("Trading output", self.trading_output_fingerprint),
            ("comparison", self.comparison_fingerprint),
        ):
            _sha(value, name)
        if self.verdict is not OnlyCalculationEquivalenceVerdict.EQUIVALENT:
            raise ValueError("only EQUIVALENT evidence can be published")
        if self.research_output_fingerprint != self.trading_output_fingerprint:
            raise ValueError("non-equivalent output identities cannot be published")
        if self.comparison_fingerprint != _comparison_fingerprint(
            self.calculation_type_reference,
            self.fixture_or_corpus_fingerprint,
            self.research_output_fingerprint,
            self.trading_output_fingerprint,
            self.equivalence_contract_version,
        ):
            raise ValueError("Equivalence comparison identity differs")

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
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyCalculationEquivalenceEvidence:
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
        if set(payload) != expected or not isinstance(payload["calculation_type_reference"], Mapping):
            raise ValueError("Equivalence Evidence fields are invalid")
        reference_payload = payload["calculation_type_reference"]
        if set(reference_payload) != {"kind", "type_id", "semantic_version"}:
            raise ValueError("Equivalence Calculation reference fields are invalid")
        from onlyalpha.calculation.definition import OnlyCalculationKind

        evidence = cls(
            OnlyCalculationTypeReference(
                OnlyCalculationKind(_string(reference_payload, "kind")),
                _string(reference_payload, "type_id"),
                _string(reference_payload, "semantic_version"),
            ),
            _string(payload, "research_implementation_fingerprint"),
            _string(payload, "trading_implementation_fingerprint"),
            _string(payload, "equivalence_contract_version"),
            _string(payload, "fixture_or_corpus_fingerprint"),
            _string(payload, "research_output_fingerprint"),
            _string(payload, "trading_output_fingerprint"),
            _string(payload, "comparison_fingerprint"),
            OnlyCalculationEquivalenceVerdict(_string(payload, "verdict")),
            _integer(payload, "schema_version"),
        )
        if payload["evidence_fingerprint"] != evidence.evidence_fingerprint:
            raise ValueError("Equivalence Evidence identity differs")
        return evidence


@dataclass(frozen=True, slots=True)
class _OnlyVerifiedCalculationEquivalenceEvidence:
    evidence: OnlyCalculationEquivalenceEvidence
    seal: object


_VERIFIER_SEAL = object()


class OnlyCalculationEquivalenceVerifier:
    def __init__(
        self,
        registry: OnlyCalculationRegistry,
        research: OnlyCalculationEquivalenceRunner,
        trading: OnlyCalculationEquivalenceRunner,
        *,
        equivalence_contract_version: str = "P9_CALCULATION_EQUIVALENCE_V1",
    ) -> None:
        if not equivalence_contract_version.strip():
            raise ValueError("Equivalence contract version is required")
        self._registry = registry
        self._research = research
        self._trading = trading
        self._contract = equivalence_contract_version

    def verify(
        self,
        reference: OnlyCalculationTypeReference,
        corpus: OnlyCalculationEquivalenceCorpus,
    ) -> _OnlyVerifiedCalculationEquivalenceEvidence:
        research_manifest = self._manifest(reference, OnlyCalculationBackendKind.RESEARCH)
        trading_manifest = self._manifest(reference, OnlyCalculationBackendKind.TRADING)
        try:
            research = self._research.execute(reference, corpus)
            trading = self._trading.execute(reference, corpus)
        except Exception as exc:
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_VERIFICATION_FAILED",
                f"backend execution failed for {reference.type_id}@{reference.semantic_version}",
            ) from exc
        if research.rows != trading.rows or research.output_fingerprint != trading.output_fingerprint:
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_VERIFICATION_FAILED",
                f"exact semantic outputs differ for {reference.type_id}@{reference.semantic_version}",
            )
        comparison = _comparison_fingerprint(
            reference,
            corpus.corpus_fingerprint,
            research.output_fingerprint,
            trading.output_fingerprint,
            self._contract,
        )
        evidence = OnlyCalculationEquivalenceEvidence(
            reference,
            research_manifest.implementation_fingerprint,
            trading_manifest.implementation_fingerprint,
            self._contract,
            corpus.corpus_fingerprint,
            research.output_fingerprint,
            trading.output_fingerprint,
            comparison,
        )
        return _OnlyVerifiedCalculationEquivalenceEvidence(evidence, _VERIFIER_SEAL)

    def _manifest(
        self,
        reference: OnlyCalculationTypeReference,
        backend: OnlyCalculationBackendKind,
    ) -> OnlyCalculationImplementationManifest:
        try:
            registration = self._registry.resolve(
                reference.kind,
                reference.type_id,
                reference.semantic_version,
                backend,
            )
        except ValueError as exc:
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_VERIFICATION_FAILED",
                f"{backend.value} backend is unavailable",
            ) from exc
        if registration.implementation_manifest is None:
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_VERIFICATION_FAILED",
                f"{backend.value} implementation identity is unavailable",
            )
        return registration.implementation_manifest


class OnlyCalculationEquivalenceEvidenceStore:
    def __init__(self, semantic_root: Path) -> None:
        self._root = semantic_root / "calculation-equivalence" / "evidence"

    def exists(self, evidence_fingerprint: str) -> bool:
        return self._target(_fingerprint(evidence_fingerprint)).is_dir()

    def commit(
        self,
        verified: _OnlyVerifiedCalculationEquivalenceEvidence,
    ) -> OnlyCalculationEquivalenceEvidence:
        if not isinstance(verified, _OnlyVerifiedCalculationEquivalenceEvidence) or verified.seal is not _VERIFIER_SEAL:
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_VERIFICATION_FAILED",
                "Evidence publication requires the verifier authority",
            )
        evidence = verified.evidence
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
            path = stage / "manifest.json"
            with path.open("x", encoding="utf-8") as stream:
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

    def load_verified(self, evidence_fingerprint: str) -> OnlyCalculationEquivalenceEvidence:
        fingerprint = _fingerprint(evidence_fingerprint)
        return self._read_verified(self._target(fingerprint), fingerprint)

    def require_verified(
        self,
        reference: OnlyCalculationTypeReference,
        research_implementation_fingerprint: str,
        trading_implementation_fingerprint: str,
    ) -> tuple[OnlyCalculationEquivalenceEvidence, ...]:
        for value in (research_implementation_fingerprint, trading_implementation_fingerprint):
            _fingerprint(value)
        if not self._root.exists():
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_EVIDENCE_NOT_FOUND",
                f"{reference.type_id}@{reference.semantic_version}",
            )
        if not self._root.is_dir() or self._root.is_symlink():
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_CORRUPT", "authority root")
        matches: list[OnlyCalculationEquivalenceEvidence] = []
        try:
            for prefix in sorted(self._root.iterdir(), key=lambda item: item.name):
                if prefix.is_symlink() or not prefix.is_dir() or len(prefix.name) != 2:
                    raise ValueError("unexpected Equivalence Evidence prefix")
                for target in sorted(prefix.iterdir(), key=lambda item: item.name):
                    evidence = self.load_verified(target.name)
                    if (
                        evidence.calculation_type_reference == reference
                        and evidence.research_implementation_fingerprint == research_implementation_fingerprint
                        and evidence.trading_implementation_fingerprint == trading_implementation_fingerprint
                    ):
                        matches.append(evidence)
        except OnlyCalculationEquivalenceError:
            raise
        except Exception as exc:
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_CORRUPT", "authority scan") from exc
        if not matches:
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_EVIDENCE_NOT_FOUND",
                f"{reference.type_id}@{reference.semantic_version}",
            )
        return tuple(sorted(matches, key=lambda item: item.evidence_fingerprint))

    def _read_verified(self, root: Path, expected_fingerprint: str) -> OnlyCalculationEquivalenceEvidence:
        if not root.is_dir():
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_NOT_FOUND", expected_fingerprint)
        try:
            manifest = root / "manifest.json"
            if root.is_symlink() or manifest.is_symlink():
                raise ValueError("Equivalence Evidence may not contain symlinks")
            if {item.name for item in root.iterdir()} != {"manifest.json"} or not manifest.is_file():
                raise ValueError("unexpected Equivalence Evidence entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, Mapping):
                raise ValueError("Equivalence Evidence manifest must be an object")
            evidence = OnlyCalculationEquivalenceEvidence.from_dict(payload)
            if evidence.evidence_fingerprint != expected_fingerprint or raw != only_canonical_json(payload):
                raise ValueError("Equivalence Evidence path/content identity differs")
            return evidence
        except OnlyCalculationEquivalenceError:
            raise
        except Exception as exc:
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_CORRUPT", expected_fingerprint) from exc

    def _target(self, fingerprint: str) -> Path:
        return self._root / fingerprint[:2] / fingerprint


def _comparison_fingerprint(
    reference: OnlyCalculationTypeReference,
    corpus_fingerprint: str,
    research_output_fingerprint: str,
    trading_output_fingerprint: str,
    contract_version: str,
) -> str:
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.calculation.equivalence-comparison",
            "schema_version": 1,
            "calculation_type_reference": {
                "kind": reference.kind.value,
                "type_id": reference.type_id,
                "semantic_version": reference.semantic_version,
            },
            "equivalence_contract_version": contract_version,
            "fixture_or_corpus_fingerprint": corpus_fingerprint,
            "research_output_fingerprint": research_output_fingerprint,
            "trading_output_fingerprint": trading_output_fingerprint,
            "comparison": "EXACT_TYPED_ROWS",
        }
    )


def _typed_value(value: object) -> object:
    if value is None:
        return {"type": "NULL", "value": None}
    if isinstance(value, bool):
        return {"type": "BOOLEAN", "value": value}
    if isinstance(value, int):
        return {"type": "INTEGER", "value": value}
    if isinstance(value, Decimal):
        return {"type": "DECIMAL", "value": format(value, "f")}
    if isinstance(value, str):
        return {"type": "STRING", "value": value}
    if isinstance(value, Mapping):
        return {
            "type": "MAPPING",
            "value": {
                str(key): _typed_value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            },
        }
    if isinstance(value, (tuple, list)):
        return {"type": "SEQUENCE", "value": [_typed_value(item) for item in value]}
    raise TypeError(f"unsupported equivalence semantic value: {type(value).__name__}")


def _fingerprint(value: str) -> str:
    try:
        _sha(value, "fingerprint")
    except (TypeError, ValueError) as exc:
        raise OnlyCalculationEquivalenceError("EQUIVALENCE_EVIDENCE_NOT_FOUND", "invalid fingerprint") from exc
    return value


def _sha(value: str, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


__all__ = [name for name in globals() if name.startswith("Only")]
