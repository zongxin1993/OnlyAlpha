"""Application boundary for researching one exact Private Strategy Revision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.quant_assets.catalog import OnlyQuantAssetCatalogGeneration
from onlyalpha.quant_assets.private import (
    OnlyPrivateAssetKind,
    OnlyPrivateAssetRevisionReferenceV1,
)
from onlyalpha.quant_assets.private_strategy import OnlyPrivateStrategyResearchContextV1
from onlyalpha.quant_assets.private_strategy_composition import (
    OnlyPrivateStrategyResearchComposer,
    OnlyPrivateStrategyResearchCompositionResult,
    OnlyPrivateStrategyResearchCompositionStore,
)
from onlyalpha.research.command.model import OnlyResearchSubmitOutcome
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.specification.model import OnlyResearchSpecification


class _ExactAuthoringGeneration(Protocol):
    def load_verified(self, fingerprint: str) -> OnlyResearchAuthoringProvenance: ...

    def load_catalog_verified(self, fingerprint: str) -> OnlyQuantAssetCatalogGeneration: ...

    def load_calculation_registry_verified(self, fingerprint: str) -> OnlyCalculationRegistry: ...


class _ResearchCommands(Protocol):
    def submit_research_run(
        self,
        submission_key: OnlyProductCommandId,
        specification: OnlyResearchSpecification,
        authoring_generation_fingerprint: str | None = None,
        *,
        strategy_research_composition_fingerprint: str | None = None,
    ) -> OnlyResearchSubmitOutcome: ...


@dataclass(frozen=True, slots=True)
class OnlyPrivateStrategyResearchRequest:
    submission_key: OnlyProductCommandId
    strategy_revision: OnlyPrivateAssetRevisionReferenceV1
    research_context: OnlyPrivateStrategyResearchContextV1
    authoring_generation_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.strategy_revision, OnlyPrivateAssetRevisionReferenceV1)
            or self.strategy_revision.private_asset_kind is not OnlyPrivateAssetKind.STRATEGY
            or not isinstance(self.research_context, OnlyPrivateStrategyResearchContextV1)
        ):
            raise ValueError("PRIVATE_STRATEGY_REVISION_INVALID")
        if self.authoring_generation_fingerprint is not None and (
            len(self.authoring_generation_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in self.authoring_generation_fingerprint)
        ):
            raise ValueError("AUTHORING_EXECUTION_GENERATION_IDENTITY_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyPrivateStrategyResearchOutcome:
    composition: OnlyPrivateStrategyResearchCompositionResult
    submission: OnlyResearchSubmitOutcome


class OnlyPrivateStrategyResearchApplicationService:
    """Compose exact Strategy intent, then submit through the existing Research authority."""

    def __init__(
        self,
        *,
        composer: OnlyPrivateStrategyResearchComposer,
        compositions: OnlyPrivateStrategyResearchCompositionStore,
        definitions: OnlyResearchDefinitionResolver,
        research: _ResearchCommands,
        authoring_generations: _ExactAuthoringGeneration | None = None,
    ) -> None:
        self._composer = composer
        self._compositions = compositions
        self._definitions = definitions
        self._research = research
        self._authoring_generations = authoring_generations

    def submit(self, request: OnlyPrivateStrategyResearchRequest) -> OnlyPrivateStrategyResearchOutcome:
        composer = self._composer
        definitions = self._definitions
        provenance: OnlyResearchAuthoringProvenance | None = None
        if self._authoring_generations is not None:
            if request.authoring_generation_fingerprint is None:
                raise ValueError("AUTHORING_EXECUTION_GENERATION_REQUIRED")
            provenance = self._authoring_generations.load_verified(request.authoring_generation_fingerprint)
            catalog = self._authoring_generations.load_catalog_verified(request.authoring_generation_fingerprint)
            if catalog.generation_fingerprint != provenance.catalog_generation_fingerprint:
                raise ValueError("AUTHORING_CATALOG_GENERATION_MISMATCH")
            composer = composer.for_catalog(catalog)
            definitions = definitions.for_calculation_registry(
                self._authoring_generations.load_calculation_registry_verified(request.authoring_generation_fingerprint)
            )
        composed = composer.compose(request.strategy_revision, request.research_context)
        if provenance is not None and (
            composed.composition.catalog_generation_fingerprint != provenance.catalog_generation_fingerprint
        ):
            raise ValueError("PRIVATE_STRATEGY_COMPOSITION_EXECUTION_CONTEXT_MISMATCH")
        resolved = definitions.resolve(composed.research_definition)
        self._compositions.put(composed.composition, request.research_context)
        submission = self._research.submit_research_run(
            request.submission_key,
            resolved.specification,
            request.authoring_generation_fingerprint,
            strategy_research_composition_fingerprint=composed.composition.composition_fingerprint,
        )
        return OnlyPrivateStrategyResearchOutcome(composed, submission)

    def submit_reference(
        self,
        submission_key: OnlyProductCommandId,
        strategy_revision: OnlyPrivateAssetRevisionReferenceV1,
        research_context: OnlyPrivateStrategyResearchContextV1,
        authoring_generation_fingerprint: str,
    ) -> OnlyPrivateStrategyResearchOutcome:
        return self.submit(
            OnlyPrivateStrategyResearchRequest(
                submission_key,
                strategy_revision,
                research_context,
                authoring_generation_fingerprint,
            )
        )


__all__ = [
    "OnlyPrivateStrategyResearchApplicationService",
    "OnlyPrivateStrategyResearchOutcome",
    "OnlyPrivateStrategyResearchRequest",
]
