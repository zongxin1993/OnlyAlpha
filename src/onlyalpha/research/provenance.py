"""Immutable authoring provenance carried by Research Runs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

_GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXPERIMENT_ID = re.compile(r"^exp-[0-9a-f]{24,64}$")


@dataclass(frozen=True, slots=True)
class OnlyResearchAuthoringProvenance:
    schema_version: int
    experiment_id: str
    source_repository: str
    source_revision: str
    source_tree: str
    candidate_provider_id: str
    candidate_provider_version: str
    candidate_provider_content_fingerprint: str
    catalog_generation_fingerprint: str
    source_locator: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not _EXPERIMENT_ID.fullmatch(self.experiment_id):
            raise ValueError("RESEARCH_PROVENANCE_INVALID")
        if not self.source_repository or not self.source_revision or not self.source_tree:
            raise ValueError("RESEARCH_PROVENANCE_INVALID")
        if not self.candidate_provider_id or not self.candidate_provider_version:
            raise ValueError("RESEARCH_PROVENANCE_INVALID")
        if not _GIT_OBJECT_ID.fullmatch(self.source_revision) or not _GIT_OBJECT_ID.fullmatch(self.source_tree):
            raise ValueError("RESEARCH_PROVENANCE_INVALID")
        if not _SHA256.fullmatch(self.candidate_provider_content_fingerprint) or not _SHA256.fullmatch(
            self.catalog_generation_fingerprint
        ):
            raise ValueError("RESEARCH_PROVENANCE_INVALID")

    def identity_dict(self) -> dict[str, object]:
        """Return authoritative provenance fields, excluding the operational locator."""

        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "source_repository": self.source_repository,
            "source_revision": self.source_revision,
            "source_tree": self.source_tree,
            "candidate_provider_id": self.candidate_provider_id,
            "candidate_provider_version": self.candidate_provider_version,
            "candidate_provider_content_fingerprint": self.candidate_provider_content_fingerprint,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
        }

    def to_dict(self) -> dict[str, object]:
        result = self.identity_dict()
        if self.source_locator is not None:
            result["source_locator"] = self.source_locator
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchAuthoringProvenance:
        return cls(
            int(cast(str | int, payload["schema_version"])),
            str(payload["experiment_id"]),
            str(payload["source_repository"]),
            str(payload["source_revision"]),
            str(payload["source_tree"]),
            str(payload["candidate_provider_id"]),
            str(payload["candidate_provider_version"]),
            str(payload["candidate_provider_content_fingerprint"]),
            str(payload["catalog_generation_fingerprint"]),
            None if payload.get("source_locator") is None else str(payload["source_locator"]),
        )


__all__ = ["OnlyResearchAuthoringProvenance"]
