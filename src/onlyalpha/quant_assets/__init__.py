"""Versioned four-kind quantitative asset provider and catalog contracts."""

from typing import TYPE_CHECKING

from .artifact import only_quant_asset_distribution_artifact_manifest as only_quant_asset_distribution_artifact_manifest
from .catalog import ONLYALPHA_QUANT_ASSET_ENTRY_POINT as ONLYALPHA_QUANT_ASSET_ENTRY_POINT
from .catalog import OnlyDistributionProviderSource as OnlyDistributionProviderSource
from .catalog import OnlyPrivateFactorSnapshotProviderSource as OnlyPrivateFactorSnapshotProviderSource
from .catalog import OnlyQuantAssetCatalogGeneration as OnlyQuantAssetCatalogGeneration
from .catalog import OnlyQuantAssetCatalogManager as OnlyQuantAssetCatalogManager
from .catalog import OnlyQuantAssetKind as OnlyQuantAssetKind
from .catalog import OnlyQuantAssetProvider as OnlyQuantAssetProvider
from .catalog import OnlyQuantAssetProviderManifest as OnlyQuantAssetProviderManifest
from .catalog import only_discover_quant_asset_providers as only_discover_quant_asset_providers
from .private import PRIVATE_ASSET_SCHEMA_VERSION as PRIVATE_ASSET_SCHEMA_VERSION
from .private import OnlyPrivateAssetAuthoringAuthority as OnlyPrivateAssetAuthoringAuthority
from .private import OnlyPrivateAssetAuthorityUnavailableError as OnlyPrivateAssetAuthorityUnavailableError
from .private import OnlyPrivateAssetConflictError as OnlyPrivateAssetConflictError
from .private import OnlyPrivateAssetCorruptError as OnlyPrivateAssetCorruptError
from .private import OnlyPrivateAssetError as OnlyPrivateAssetError
from .private import OnlyPrivateAssetInvalidError as OnlyPrivateAssetInvalidError
from .private import OnlyPrivateAssetKind as OnlyPrivateAssetKind
from .private import OnlyPrivateAssetKindUnsupportedError as OnlyPrivateAssetKindUnsupportedError
from .private import OnlyPrivateAssetNotFoundError as OnlyPrivateAssetNotFoundError
from .private import OnlyPrivateAssetParentMismatchError as OnlyPrivateAssetParentMismatchError
from .private import OnlyPrivateAssetPutDisposition as OnlyPrivateAssetPutDisposition
from .private import OnlyPrivateAssetReferenceMismatchError as OnlyPrivateAssetReferenceMismatchError
from .private import OnlyPrivateAssetRevisionBindingResolver as OnlyPrivateAssetRevisionBindingResolver
from .private import OnlyPrivateAssetRevisionCorruptError as OnlyPrivateAssetRevisionCorruptError
from .private import OnlyPrivateAssetRevisionNotFoundError as OnlyPrivateAssetRevisionNotFoundError
from .private import OnlyPrivateAssetRevisionReferenceV1 as OnlyPrivateAssetRevisionReferenceV1
from .private import OnlyPrivateAssetSchemaUnsupportedError as OnlyPrivateAssetSchemaUnsupportedError
from .private import OnlyPrivateAssetStaleBaseError as OnlyPrivateAssetStaleBaseError
from .private import OnlyPrivateFactorAsset as OnlyPrivateFactorAsset
from .private import OnlyPrivateFactorDraft as OnlyPrivateFactorDraft
from .private import OnlyPrivateFactorRevision as OnlyPrivateFactorRevision
from .private import OnlyPrivateStrategyAsset as OnlyPrivateStrategyAsset
from .private import OnlyPrivateStrategyDraft as OnlyPrivateStrategyDraft
from .private import OnlyPrivateStrategyRevision as OnlyPrivateStrategyRevision
from .private import OnlyVerifiedPrivateAssetRevisionBindingV1 as OnlyVerifiedPrivateAssetRevisionBindingV1
from .private import only_private_factor_revision_fingerprint as only_private_factor_revision_fingerprint
from .private import only_private_factor_source_sha256 as only_private_factor_source_sha256
from .private import only_private_strategy_definition_fingerprint as only_private_strategy_definition_fingerprint
from .private import only_private_strategy_revision_fingerprint as only_private_strategy_revision_fingerprint
from .private_factor_provider_snapshot import (
    OnlyPrivateFactorProviderSnapshotEntryV1 as OnlyPrivateFactorProviderSnapshotEntryV1,
)
from .private_factor_provider_snapshot import (
    OnlyPrivateFactorProviderSnapshotV1 as OnlyPrivateFactorProviderSnapshotV1,
)

if TYPE_CHECKING:
    from .example_seed import OnlyPrivateAssetExampleBundleV1 as OnlyPrivateAssetExampleBundleV1
    from .example_seed import OnlyPrivateAssetExampleImporterV1 as OnlyPrivateAssetExampleImporterV1
    from .example_seed import only_load_private_asset_example_bundle as only_load_private_asset_example_bundle
    from .private_factor_execution import ONLY_PRIVATE_FACTOR_API_V1 as ONLY_PRIVATE_FACTOR_API_V1
    from .private_factor_execution import (
        ONLY_PRIVATE_FACTOR_VALIDATION_POLICY_V1 as ONLY_PRIVATE_FACTOR_VALIDATION_POLICY_V1,
    )
    from .private_factor_execution import OnlyPrivateFactorAdapterV1 as OnlyPrivateFactorAdapterV1
    from .private_factor_execution import OnlyPrivateFactorApiContractV1 as OnlyPrivateFactorApiContractV1
    from .private_factor_execution import OnlyPrivateFactorExecutableClosureV1 as OnlyPrivateFactorExecutableClosureV1
    from .private_factor_execution import OnlyPrivateFactorIsolatedProgramHost as OnlyPrivateFactorIsolatedProgramHost
    from .private_factor_execution import (
        OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1 as OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1,
    )
    from .private_factor_execution import (
        OnlyPrivateFactorSourceArtifactManifestV1 as OnlyPrivateFactorSourceArtifactManifestV1,
    )
    from .private_factor_execution import (
        OnlyPrivateFactorValidationDisposition as OnlyPrivateFactorValidationDisposition,
    )
    from .private_factor_execution import OnlyPrivateFactorValidationEvidenceV1 as OnlyPrivateFactorValidationEvidenceV1
    from .private_factor_execution import OnlyPrivateFactorValidationPolicyV1 as OnlyPrivateFactorValidationPolicyV1
    from .private_factor_execution import (
        only_private_factor_backend_registrations as only_private_factor_backend_registrations,
    )
    from .private_factor_execution import only_private_factor_type_definition as only_private_factor_type_definition
    from .private_factor_execution import only_validate_private_factor_revision as only_validate_private_factor_revision

_LAZY_EXECUTION_EXPORTS = {
    name: ("private_factor_execution", name)
    for name in (
        "ONLY_PRIVATE_FACTOR_API_V1",
        "ONLY_PRIVATE_FACTOR_VALIDATION_POLICY_V1",
        "OnlyPrivateFactorAdapterV1",
        "OnlyPrivateFactorApiContractV1",
        "OnlyPrivateFactorExecutableClosureV1",
        "OnlyPrivateFactorIsolatedProgramHost",
        "OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1",
        "OnlyPrivateFactorSourceArtifactManifestV1",
        "OnlyPrivateFactorValidationDisposition",
        "OnlyPrivateFactorValidationEvidenceV1",
        "OnlyPrivateFactorValidationPolicyV1",
        "only_private_factor_backend_registrations",
        "only_private_factor_type_definition",
        "only_validate_private_factor_revision",
    )
}
_LAZY_EXECUTION_EXPORTS.update(
    {
        name: ("example_seed", name)
        for name in (
            "OnlyPrivateAssetExampleBundleV1",
            "OnlyPrivateAssetExampleImporterV1",
            "only_load_private_asset_example_bundle",
        )
    }
)

_LAZY_STRATEGY_EXPORTS = {
    "PRIVATE_STRATEGY_DEFINITION_SCHEMA_VERSION": ("private_strategy", "PRIVATE_STRATEGY_DEFINITION_SCHEMA_VERSION"),
    "PRIVATE_STRATEGY_RESEARCH_CONTEXT_SCHEMA_VERSION": (
        "private_strategy",
        "PRIVATE_STRATEGY_RESEARCH_CONTEXT_SCHEMA_VERSION",
    ),
    "OnlyPrivateStrategyDefinitionV1": ("private_strategy", "OnlyPrivateStrategyDefinitionV1"),
    "OnlyPrivateStrategyFactorRevisionDependencyV1": (
        "private_strategy",
        "OnlyPrivateStrategyFactorRevisionDependencyV1",
    ),
    "OnlyPrivateStrategyResearchContextV1": ("private_strategy", "OnlyPrivateStrategyResearchContextV1"),
    "PRIVATE_STRATEGY_COMPOSITION_SCHEMA_VERSION": (
        "private_strategy_composition",
        "PRIVATE_STRATEGY_COMPOSITION_SCHEMA_VERSION",
    ),
    "OnlyInMemoryPrivateStrategyResearchCompositionStore": (
        "private_strategy_composition",
        "OnlyInMemoryPrivateStrategyResearchCompositionStore",
    ),
    "OnlyPrivateStrategyResearchCompositionError": (
        "private_strategy_composition",
        "OnlyPrivateStrategyResearchCompositionError",
    ),
    "OnlyPrivateStrategyResearchCompositionResult": (
        "private_strategy_composition",
        "OnlyPrivateStrategyResearchCompositionResult",
    ),
    "OnlyPrivateStrategyResearchCompositionStore": (
        "private_strategy_composition",
        "OnlyPrivateStrategyResearchCompositionStore",
    ),
    "OnlyPrivateStrategyResearchCompositionV1": (
        "private_strategy_composition",
        "OnlyPrivateStrategyResearchCompositionV1",
    ),
    "OnlyPrivateStrategyResearchComposer": ("private_strategy_composition", "OnlyPrivateStrategyResearchComposer"),
    "OnlyPrivateStrategyResearchCompositionVerifier": (
        "private_strategy_composition",
        "OnlyPrivateStrategyResearchCompositionVerifier",
    ),
}


def __getattr__(name: str) -> object:
    target = _LAZY_STRATEGY_EXPORTS.get(name) or _LAZY_EXECUTION_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    from importlib import import_module

    value = getattr(import_module(f"{__name__}.{target[0]}"), target[1])
    globals()[name] = value
    return value


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "ONLYALPHA_"))]
__all__ += sorted(_LAZY_STRATEGY_EXPORTS)
__all__ += sorted(name for name in _LAZY_EXECUTION_EXPORTS if name.startswith(("Only", "only_", "ONLYALPHA_")))
