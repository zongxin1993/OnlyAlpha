"""DB-native Private Alpha public-contract conformance."""

from __future__ import annotations

from decimal import Decimal

import pytest

from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationKind
from onlyalpha.quant_assets import (
    ONLY_PRIVATE_ALPHA_API_V1,
    OnlyPrivateAlphaDraft,
    OnlyPrivateAlphaExecutableClosureV1,
    OnlyPrivateAlphaRevision,
    OnlyPrivateAlphaSnapshotProviderSource,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)

pytestmark = pytest.mark.contract


def _closure() -> OnlyPrivateAlphaExecutableClosureV1:
    revision = OnlyPrivateAlphaRevision.from_draft(
        OnlyPrivateAlphaDraft(
            alpha_id="private.alpha.contract",
            semantic_version="1",
            source_text='def calculate(api, inputs, parameters):\n    return {"value": api.add(inputs["close"], parameters["offset"])}\n',
            alpha_api_version=1,
            alpha_api_contract_fingerprint=ONLY_PRIVATE_ALPHA_API_V1.api_contract_fingerprint,
            input_contract={"close": {"type": "DECIMAL"}},
            parameter_contract={"offset": {"type": "DECIMAL"}},
            output_contract={"value": {"type": "DECIMAL"}},
            description="Contract Alpha",
            economic_rationale="Contract witness",
            category="reference",
        )
    )
    return OnlyPrivateAlphaExecutableClosureV1.create(
        revision,
        ({"close": Decimal("1")},),
        {"offset": Decimal("2")},
    )


def test_native_alpha_uses_one_public_catalog_and_calculation_registry_contract() -> None:
    closure = _closure()
    provider = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            "private.alpha.contract.provider",
            closure.revision.revision_fingerprint,
            OnlyQuantAssetKind.ALPHA,
            OnlyPrivateAlphaSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
        ),
        calculation_registrations=closure.registrations,
        private_alpha_snapshot=closure.provider_snapshot,
    )
    catalog = OnlyQuantAssetCatalogGeneration((provider,))
    registry = catalog.calculation_registry()

    assert catalog.providers == (provider,)
    assert provider.manifest.kind is OnlyQuantAssetKind.ALPHA
    for backend in (OnlyCalculationBackendKind.RESEARCH, OnlyCalculationBackendKind.TRADING):
        registration = registry.resolve(OnlyCalculationKind.FACTOR, closure.revision.alpha_id, "1", backend)
        assert registration in closure.registrations
        assert registration.implementation_manifest is not None
        assert any(
            dependency.dependency_id == "onlyalpha.private-alpha.source-artifact"
            and dependency.artifact_fingerprint == closure.source_artifact.source_artifact_fingerprint
            for dependency in registration.implementation_manifest.semantic_dependencies
        )


def test_snapshot_provider_rejects_distribution_identity_access() -> None:
    closure = _closure()
    manifest = OnlyQuantAssetProviderManifest(
        "private.alpha.contract.provider",
        closure.revision.revision_fingerprint,
        OnlyQuantAssetKind.ALPHA,
        OnlyPrivateAlphaSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
    )

    with pytest.raises(ValueError, match="NOT_DISTRIBUTION_BACKED"):
        _ = manifest.distribution_name
