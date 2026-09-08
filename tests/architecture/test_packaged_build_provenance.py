from __future__ import annotations

import json
from pathlib import Path

import pytest

from onlyalpha.build_provenance import OnlyPackagedBuildProvenanceV1, only_packaged_build_provenance
from onlyalpha.distribution import OnlyArtifactSourceProvenanceAuthority
from scripts.embed_build_provenance import build_provenance_bytes, resolve_build_source_revision

pytestmark = pytest.mark.architecture


def test_packaged_build_provenance_is_exact_offline_distribution_metadata() -> None:
    value = only_packaged_build_provenance()
    assert value.source_provenance_authority is OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT
    assert value.source_repository == "OnlyAlpha"
    assert value.distribution_name == "onlyalpha"
    assert len(value.source_revision) == 40


def test_build_step_emits_canonical_provenance_and_rejects_missing_revision(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    revision = "1" * 40
    payload = json.loads(build_provenance_bytes(repository, revision))
    assert payload == {
        "distribution_name": "onlyalpha",
        "distribution_version": "0.9.9",
        "schema_version": 1,
        "source_provenance_authority": "ONLYALPHA_GIT",
        "source_repository": "OnlyAlpha",
        "source_revision": revision,
    }
    with pytest.raises(ValueError, match="ONLYALPHA_BUILD_SOURCE_REVISION_INVALID"):
        resolve_build_source_revision(tmp_path, "mutable-main")


def test_malformed_packaged_build_provenance_fails_closed() -> None:
    with pytest.raises(ValueError, match="ONLYALPHA_BUILD_PROVENANCE_INVALID"):
        OnlyPackagedBuildProvenanceV1(
            OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
            "OnlyAlpha",
            "unknown",
            "onlyalpha",
            "0.9.9",
        )
