from __future__ import annotations

import pytest

from onlyalpha.quant_assets import OnlyPrivateAssetKind
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    only_research_execution_generation_fingerprint,
)


def _provenance() -> OnlyResearchAuthoringProvenance:
    values = {
        "experiment_id": "exp-" + "b" * 32,
        "private_asset_kind": OnlyPrivateAssetKind.ALPHA,
        "private_asset_id": "private.alpha.momentum",
        "private_asset_revision_fingerprint": "5" * 64,
        "private_asset_content_fingerprint": "6" * 64,
        "candidate_provider_id": "candidate.private.alpha",
        "candidate_provider_version": "7",
        "candidate_provider_content_fingerprint": "8" * 64,
        "catalog_generation_fingerprint": "9" * 64,
    }
    return OnlyResearchAuthoringProvenance(
        schema_version=1,
        **values,
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(**values),
    )


def test_db_native_provenance_round_trip_and_generation_identity_are_deterministic() -> None:
    provenance = _provenance()
    assert provenance.execution_generation_fingerprint == (
        "de56afec973b2052a99d502b7a701040abd4906711631596adb2618df5121783"
    )
    assert OnlyResearchAuthoringProvenance.from_dict(provenance.to_dict()) == provenance


def test_git_native_and_malformed_db_native_payloads_are_rejected() -> None:
    git_native = {
        "schema_version": 1,
        "experiment_id": "exp-" + "a" * 32,
        "source_repository": "OnlyAlpha-alpha",
        "source_revision": "1" * 40,
        "source_tree": "2" * 40,
        "candidate_provider_id": "candidate.private.alpha",
        "candidate_provider_version": "1",
        "candidate_provider_content_fingerprint": "3" * 64,
        "catalog_generation_fingerprint": "4" * 64,
        "execution_generation_fingerprint": "5" * 64,
    }
    with pytest.raises(ValueError, match="PROVENANCE_INVALID"):
        OnlyResearchAuthoringProvenance.from_dict(git_native)

    for field in ("private_asset_revision_fingerprint", "private_asset_content_fingerprint"):
        payload = _provenance().to_dict()
        payload[field] = "not-a-fingerprint"
        with pytest.raises(ValueError, match="PROVENANCE_INVALID"):
            OnlyResearchAuthoringProvenance.from_dict(payload)


@pytest.mark.parametrize("schema_version", [0, 2, "1", True, None])
def test_noncanonical_schema_version_is_rejected(schema_version: object) -> None:
    payload = _provenance().to_dict()
    payload["schema_version"] = schema_version
    with pytest.raises(ValueError, match="PROVENANCE_INVALID"):
        OnlyResearchAuthoringProvenance.from_dict(payload)
