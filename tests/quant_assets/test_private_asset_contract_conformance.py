"""DB-native Private Factor public-contract conformance."""

from __future__ import annotations

from decimal import Decimal

import pytest

from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationKind
from onlyalpha.quant_assets import (
    ONLY_PRIVATE_FACTOR_API_V1,
    OnlyPrivateFactorDraft,
    OnlyPrivateFactorExecutableClosureV1,
    OnlyPrivateFactorRevision,
    OnlyPrivateFactorSnapshotProviderSource,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)

pytestmark = pytest.mark.contract


def _closure() -> OnlyPrivateFactorExecutableClosureV1:
    revision = OnlyPrivateFactorRevision.from_draft(
        OnlyPrivateFactorDraft(
            factor_id="private.factor.contract",
            semantic_version="1",
            source_text='def calculate(api, inputs, parameters):\n    return {"value": api.add(inputs["close"], parameters["offset"])}\n',
            factor_api_version=1,
            factor_api_contract_fingerprint=ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
            input_contract={"close": {"type": "DECIMAL"}},
            parameter_contract={"offset": {"type": "DECIMAL"}},
            output_contract={"value": {"type": "DECIMAL"}},
            description="Contract Factor",
            economic_rationale="Contract witness",
            category="reference",
        )
    )
    return OnlyPrivateFactorExecutableClosureV1.create(
        revision,
        ({"close": Decimal("1")},),
        {"offset": Decimal("2")},
    )


def test_native_factor_uses_one_public_catalog_and_calculation_registry_contract() -> None:
    closure = _closure()
    provider = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            "private.factor.contract.provider",
            closure.revision.revision_fingerprint,
            OnlyQuantAssetKind.FACTOR,
            OnlyPrivateFactorSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
        ),
        calculation_registrations=closure.registrations,
        private_factor_snapshot=closure.provider_snapshot,
    )
    catalog = OnlyQuantAssetCatalogGeneration((provider,))
    registry = catalog.calculation_registry()

    assert catalog.providers == (provider,)
    assert provider.manifest.kind is OnlyQuantAssetKind.FACTOR
    for backend in (OnlyCalculationBackendKind.RESEARCH, OnlyCalculationBackendKind.TRADING):
        registration = registry.resolve(OnlyCalculationKind.FACTOR, closure.revision.factor_id, "1", backend)
        assert registration in closure.registrations
        assert registration.implementation_manifest is not None
        assert any(
            dependency.dependency_id == "onlyalpha.private-factor.source-artifact"
            and dependency.artifact_fingerprint == closure.source_artifact.source_artifact_fingerprint
            for dependency in registration.implementation_manifest.semantic_dependencies
        )


def test_snapshot_provider_rejects_distribution_identity_access() -> None:
    closure = _closure()
    manifest = OnlyQuantAssetProviderManifest(
        "private.factor.contract.provider",
        closure.revision.revision_fingerprint,
        OnlyQuantAssetKind.FACTOR,
        OnlyPrivateFactorSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
    )

    with pytest.raises(ValueError, match="NOT_DISTRIBUTION_BACKED"):
        _ = manifest.distribution_name
