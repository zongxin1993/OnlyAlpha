"""Pure immutable Private Factor provider snapshot identity and read contracts."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from onlyalpha.calculation.implementation import OnlyCalculationImplementationManifest
from onlyalpha.canonical import only_canonical_fingerprint

if TYPE_CHECKING:
    from .private_factor_execution import (
        OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1,
        OnlyPrivateFactorSourceArtifactManifestV1,
    )


@dataclass(frozen=True, order=True, slots=True)
class OnlyPrivateFactorProviderSnapshotEntryV1:
    factor_id: str
    semantic_version: str
    revision_fingerprint: str
    source_sha256: str
    source_artifact_fingerprint: str
    factor_api_version: int
    factor_api_contract_fingerprint: str
    research_adapter_fingerprint: str
    trading_adapter_fingerprint: str
    research_implementation_fingerprint: str
    trading_implementation_fingerprint: str
    equivalence_evidence_fingerprint: str

    def __post_init__(self) -> None:
        for value in (self.factor_id, self.semantic_version):
            if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,255}", value) is None:
                raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        if type(self.factor_api_version) is not int or self.factor_api_version < 1:
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        for name in self.__dataclass_fields__:
            if name not in {"factor_id", "semantic_version", "factor_api_version"}:
                value = getattr(self, name)
                if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                    raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")

    @classmethod
    def derive(
        cls,
        manifest: OnlyPrivateFactorSourceArtifactManifestV1,
        evidence: OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1,
    ) -> OnlyPrivateFactorProviderSnapshotEntryV1:
        if (
            evidence.revision_fingerprint != manifest.revision_fingerprint
            or evidence.source_artifact_fingerprint != manifest.source_artifact_fingerprint
            or evidence.factor_api_contract_fingerprint != manifest.factor_api_contract_fingerprint
            or evidence.disposition != "PASS"
        ):
            raise ValueError("PRIVATE_FACTOR_EQUIVALENCE_EVIDENCE_MISMATCH")
        return cls(
            manifest.factor_id,
            manifest.semantic_version,
            manifest.revision_fingerprint,
            manifest.source_sha256,
            manifest.source_artifact_fingerprint,
            manifest.factor_api_version,
            manifest.factor_api_contract_fingerprint,
            evidence.research_adapter_fingerprint,
            evidence.trading_adapter_fingerprint,
            evidence.research_implementation_fingerprint,
            evidence.trading_implementation_fingerprint,
            evidence.equivalence_evidence_fingerprint,
        )

    def to_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    def require_implementation_manifest(self, manifest: OnlyCalculationImplementationManifest) -> None:
        """Check source/API/adapter relations without reading or executing unretained bytes."""
        if (
            type(manifest) is not OnlyCalculationImplementationManifest
            or OnlyCalculationImplementationManifest.from_dict(manifest.to_dict()) != manifest
        ):
            raise ValueError("PRIVATE_FACTOR_IMPLEMENTATION_MANIFEST_MISMATCH")
        reference = manifest.calculation_type_reference
        backend = manifest.backend_kind.value
        if (
            (reference.kind.value, reference.type_id, reference.semantic_version)
            != ("FACTOR", self.factor_id, self.semantic_version)
            or backend not in {"RESEARCH", "TRADING"}
            or self.factor_api_version != 1
        ):
            raise ValueError("PRIVATE_FACTOR_IMPLEMENTATION_MANIFEST_MISMATCH")
        expected_implementation = (
            self.research_implementation_fingerprint
            if backend == "RESEARCH"
            else self.trading_implementation_fingerprint
        )
        adapter_identity = (
            self.research_adapter_fingerprint if backend == "RESEARCH" else self.trading_adapter_fingerprint
        )
        entrypoint = (
            "OnlyPrivateFactorResearchBackendV1"
            if backend == "RESEARCH"
            else "OnlyPrivateFactorTradingBackendFactoryV1"
        )
        if (
            manifest.implementation_fingerprint != expected_implementation
            or manifest.entrypoint_identity != f"onlyalpha.quant_assets.private_factor_execution:{entrypoint}"
        ):
            raise ValueError("PRIVATE_FACTOR_IMPLEMENTATION_MANIFEST_MISMATCH")
        resources = {item.relative_path: item.byte_sha256 for item in manifest.resources}
        prefix = f"private_factor/{backend.lower()}"
        if (
            set(resources) != {"private_factor/source.py", f"{prefix}-adapter.py", f"{prefix}-identity.txt"}
            or resources["private_factor/source.py"] != self.source_sha256
            or resources[f"{prefix}-identity.txt"] != hashlib.sha256(adapter_identity.encode("ascii")).hexdigest()
        ):
            raise ValueError("PRIVATE_FACTOR_IMPLEMENTATION_MANIFEST_MISMATCH")
        dependencies = {
            (item.dependency_id, item.semantic_version, item.artifact_fingerprint)
            for item in manifest.semantic_dependencies
        }
        if dependencies != {
            ("onlyalpha.private-factor.api", "1", self.factor_api_contract_fingerprint),
            ("onlyalpha.private-factor.source-artifact", "1", self.source_artifact_fingerprint),
        } or len(dependencies) != len(manifest.semantic_dependencies):
            raise ValueError("PRIVATE_FACTOR_IMPLEMENTATION_MANIFEST_MISMATCH")

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateFactorProviderSnapshotEntryV1:
        if set(payload) != set(cls.__dataclass_fields__):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        values = [payload[field] for field in cls.__dataclass_fields__]
        if any(not isinstance(value, str) for value in values[:5] + values[6:]):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        if isinstance(values[5], bool) or not isinstance(values[5], int):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        return cls(*cast(list[Any], values))


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorProviderSnapshotV1:
    entries: tuple[OnlyPrivateFactorProviderSnapshotEntryV1, ...]

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.entries))
        if not canonical or len({item.factor_id for item in canonical}) != len(canonical):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        object.__setattr__(self, "entries", canonical)

    @property
    def snapshot_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "contract": "ONLYALPHA_PRIVATE_FACTOR_PROVIDER_SNAPSHOT_V1",
                "entries": [item.to_dict() for item in self.entries],
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "entries": [item.to_dict() for item in self.entries],
            "snapshot_fingerprint": self.snapshot_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateFactorProviderSnapshotV1:
        if set(payload) != {"entries", "snapshot_fingerprint"} or not isinstance(payload["entries"], list):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        result = cls(
            tuple(
                OnlyPrivateFactorProviderSnapshotEntryV1.from_dict(cast(Mapping[str, object], item))
                for item in payload["entries"]
                if isinstance(item, Mapping)
            )
        )
        if (
            len(result.entries) != len(payload["entries"])
            or payload["snapshot_fingerprint"] != result.snapshot_fingerprint
            or result.to_dict() != payload
        ):
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_INVALID")
        return result
