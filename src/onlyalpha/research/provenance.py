"""Immutable DB-native authoring provenance carried by Research Runs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.quant_assets.private import OnlyPrivateAssetKind, OnlyPrivateFactorAsset, OnlyPrivateStrategyAsset

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXPERIMENT_ID = re.compile(r"^exp-[0-9a-f]{24,64}$")


@dataclass(frozen=True, slots=True)
class OnlyResearchAuthoringProvenance:
    schema_version: int
    experiment_id: str
    private_asset_kind: OnlyPrivateAssetKind
    private_asset_id: str
    private_asset_revision_fingerprint: str
    private_asset_content_fingerprint: str
    candidate_provider_id: str
    candidate_provider_version: str
    candidate_provider_content_fingerprint: str
    catalog_generation_fingerprint: str
    execution_generation_fingerprint: str

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or _EXPERIMENT_ID.fullmatch(self.experiment_id) is None
            or not self.candidate_provider_id
            or not self.candidate_provider_version
            or not isinstance(self.private_asset_kind, OnlyPrivateAssetKind)
        ):
            raise ValueError("RESEARCH_PROVENANCE_INVALID")
        if self.private_asset_kind is OnlyPrivateAssetKind.FACTOR:
            OnlyPrivateFactorAsset(self.private_asset_id)
        else:
            OnlyPrivateStrategyAsset(self.private_asset_id)
        if not all(
            _SHA256.fullmatch(value) is not None
            for value in (
                self.private_asset_revision_fingerprint,
                self.private_asset_content_fingerprint,
                self.candidate_provider_content_fingerprint,
                self.catalog_generation_fingerprint,
                self.execution_generation_fingerprint,
            )
        ):
            raise ValueError("RESEARCH_PROVENANCE_INVALID")
        if self.execution_generation_fingerprint != only_research_execution_generation_fingerprint(
            experiment_id=self.experiment_id,
            private_asset_kind=self.private_asset_kind,
            private_asset_id=self.private_asset_id,
            private_asset_revision_fingerprint=self.private_asset_revision_fingerprint,
            private_asset_content_fingerprint=self.private_asset_content_fingerprint,
            candidate_provider_id=self.candidate_provider_id,
            candidate_provider_version=self.candidate_provider_version,
            candidate_provider_content_fingerprint=self.candidate_provider_content_fingerprint,
            catalog_generation_fingerprint=self.catalog_generation_fingerprint,
        ):
            raise ValueError("RESEARCH_EXECUTION_GENERATION_MISMATCH")

    def identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "private_asset_kind": self.private_asset_kind.value,
            "private_asset_id": self.private_asset_id,
            "private_asset_revision_fingerprint": self.private_asset_revision_fingerprint,
            "private_asset_content_fingerprint": self.private_asset_content_fingerprint,
            "candidate_provider_id": self.candidate_provider_id,
            "candidate_provider_version": self.candidate_provider_version,
            "candidate_provider_content_fingerprint": self.candidate_provider_content_fingerprint,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "execution_generation_fingerprint": self.execution_generation_fingerprint,
        }

    def to_dict(self) -> dict[str, object]:
        return self.identity_dict()

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchAuthoringProvenance:
        expected = {
            "schema_version",
            "experiment_id",
            "private_asset_kind",
            "private_asset_id",
            "private_asset_revision_fingerprint",
            "private_asset_content_fingerprint",
            "candidate_provider_id",
            "candidate_provider_version",
            "candidate_provider_content_fingerprint",
            "catalog_generation_fingerprint",
            "execution_generation_fingerprint",
        }
        if set(payload) != expected:
            raise ValueError("RESEARCH_PROVENANCE_INVALID")
        try:
            kind = OnlyPrivateAssetKind(_strict_string(payload["private_asset_kind"]))
        except ValueError as exc:
            raise ValueError("RESEARCH_PROVENANCE_INVALID") from exc
        return cls(
            _strict_schema_version(payload["schema_version"]),
            _strict_string(payload["experiment_id"]),
            kind,
            _strict_string(payload["private_asset_id"]),
            _strict_string(payload["private_asset_revision_fingerprint"]),
            _strict_string(payload["private_asset_content_fingerprint"]),
            _strict_string(payload["candidate_provider_id"]),
            _strict_string(payload["candidate_provider_version"]),
            _strict_string(payload["candidate_provider_content_fingerprint"]),
            _strict_string(payload["catalog_generation_fingerprint"]),
            _strict_string(payload["execution_generation_fingerprint"]),
        )


def _strict_schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise ValueError("RESEARCH_PROVENANCE_INVALID")
    return value


def _strict_string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("RESEARCH_PROVENANCE_INVALID")
    return value


def only_research_execution_generation_fingerprint(
    *,
    experiment_id: str,
    private_asset_kind: OnlyPrivateAssetKind,
    private_asset_id: str,
    private_asset_revision_fingerprint: str,
    private_asset_content_fingerprint: str,
    candidate_provider_id: str,
    candidate_provider_version: str,
    candidate_provider_content_fingerprint: str,
    catalog_generation_fingerprint: str,
) -> str:
    return only_canonical_fingerprint(
        {
            "contract": "ONLYALPHA_DB_NATIVE_AUTHORING_EXECUTION_GENERATION_V1",
            "experiment_id": experiment_id,
            "private_asset_kind": private_asset_kind.value,
            "private_asset_id": private_asset_id,
            "private_asset_revision_fingerprint": private_asset_revision_fingerprint,
            "private_asset_content_fingerprint": private_asset_content_fingerprint,
            "candidate_provider_id": candidate_provider_id,
            "candidate_provider_version": candidate_provider_version,
            "candidate_provider_content_fingerprint": candidate_provider_content_fingerprint,
            "catalog_generation_fingerprint": catalog_generation_fingerprint,
        }
    )


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
