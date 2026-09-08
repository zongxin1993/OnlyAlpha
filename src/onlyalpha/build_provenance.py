"""Offline-readable source provenance embedded in the OnlyAlpha artifact."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import metadata, resources
from typing import cast

from onlyalpha.distribution import OnlyArtifactSourceProvenanceAuthority

_GIT_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_RESOURCE = "_build_provenance.json"


@dataclass(frozen=True, slots=True)
class OnlyPackagedBuildProvenanceV1:
    """The canonical source-provenance fields carried by one built distribution."""

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
            or self.distribution_name != "onlyalpha"
            or not self.distribution_version
            or _GIT_REVISION.fullmatch(self.source_revision) is None
        ):
            raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID")

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> OnlyPackagedBuildProvenanceV1:
        if set(payload) != {
            "schema_version",
            "source_provenance_authority",
            "source_repository",
            "source_revision",
            "distribution_name",
            "distribution_version",
        }:
            raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID")
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
            raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID")
        string_values = {field: cast(str, payload[field]) for field in string_fields}
        try:
            authority = OnlyArtifactSourceProvenanceAuthority(string_values["source_provenance_authority"])
        except ValueError as exc:
            raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID") from exc
        return cls(
            authority,
            string_values["source_repository"],
            string_values["source_revision"],
            string_values["distribution_name"],
            string_values["distribution_version"],
            schema_version,
        )


def only_packaged_build_provenance() -> OnlyPackagedBuildProvenanceV1:
    """Load exact build provenance without consulting Git, a network, or mutable state."""

    try:
        raw = resources.files("onlyalpha").joinpath(_RESOURCE).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_UNAVAILABLE") from exc
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID") from exc
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID")
    value = OnlyPackagedBuildProvenanceV1.from_dict(cast(dict[str, object], payload))
    try:
        installed_version = metadata.version(value.distribution_name)
    except metadata.PackageNotFoundError as exc:
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_UNAVAILABLE") from exc
    if installed_version != value.distribution_version:
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID")
    return value


__all__ = ["OnlyPackagedBuildProvenanceV1", "only_packaged_build_provenance"]
