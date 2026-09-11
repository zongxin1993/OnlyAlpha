"""Offline-readable immutable provenance for the Orchestrator distribution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import metadata, resources
from typing import cast

from onlyalpha.distribution import OnlyArtifactSourceProvenanceAuthority

_GIT_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_RESOURCE = "_build_provenance.json"
_DISTRIBUTION = "onlyalpha-agent-orchestrator"


@dataclass(frozen=True, slots=True)
class OnlyAgentOrchestratorPackagedBuildProvenanceV1:
    """Canonical build fact carried by the independently built Orchestrator."""

    source_provenance_authority: OnlyArtifactSourceProvenanceAuthority
    source_repository: str
    source_revision: str
    distribution_name: str
    distribution_version: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or self.source_provenance_authority is not OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT
            or self.source_repository != "OnlyAlpha"
            or self.distribution_name != _DISTRIBUTION
            or not self.distribution_version
            or _GIT_REVISION.fullmatch(self.source_revision) is None
        ):
            raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "schema_version": self.schema_version,
            "source_provenance_authority": self.source_provenance_authority.value,
            "source_repository": self.source_repository,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> OnlyAgentOrchestratorPackagedBuildProvenanceV1:
        if set(payload) != {
            "schema_version",
            "source_provenance_authority",
            "source_repository",
            "source_revision",
            "distribution_name",
            "distribution_version",
        }:
            raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID")
        schema_version = payload["schema_version"]
        string_fields = (
            "source_provenance_authority",
            "source_repository",
            "source_revision",
            "distribution_name",
            "distribution_version",
        )
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or any(not isinstance(payload[field], str) for field in string_fields)
        ):
            raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID")
        values = {field: cast(str, payload[field]) for field in string_fields}
        try:
            authority = OnlyArtifactSourceProvenanceAuthority(values["source_provenance_authority"])
        except ValueError as exc:
            raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID") from exc
        return cls(
            authority,
            values["source_repository"],
            values["source_revision"],
            values["distribution_name"],
            values["distribution_version"],
            schema_version,
        )


def only_agent_orchestrator_packaged_build_provenance() -> OnlyAgentOrchestratorPackagedBuildProvenanceV1:
    """Exact-load build provenance without Git, network, or source-tree fallback."""

    try:
        raw = resources.files("onlyalpha_agent_orchestrator").joinpath(_RESOURCE).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_UNAVAILABLE") from exc
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID") from exc
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID")
    value = OnlyAgentOrchestratorPackagedBuildProvenanceV1.from_dict(cast(dict[str, object], payload))
    canonical = (json.dumps(value.to_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode()
    if raw != canonical:
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID")
    try:
        installed_version = metadata.version(value.distribution_name)
    except metadata.PackageNotFoundError as exc:
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_UNAVAILABLE") from exc
    if installed_version != value.distribution_version:
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID")
    return value


__all__ = [
    "OnlyAgentOrchestratorPackagedBuildProvenanceV1",
    "only_agent_orchestrator_packaged_build_provenance",
]
