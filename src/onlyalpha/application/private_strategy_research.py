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
from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.runtime.generation import OnlyRuntimeGenerationManifest


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
        runtime_generation_fingerprint: str | None = None,
        strategy_research_composition_fingerprint: str | None = None,
    ) -> OnlyResearchSubmitOutcome: ...


class _ExactRuntimeGenerations(Protocol):
    def require_runtime_generation(self, fingerprint: str) -> OnlyRuntimeGenerationManifest: ...


@dataclass(frozen=True, slots=True)
class OnlyPrivateStrategyResearchRequest:
    submission_key: OnlyProductCommandId
    strategy_revision: OnlyPrivateAssetRevisionReferenceV1
    research_context: OnlyPrivateStrategyResearchContextV1
    runtime_generation_fingerprint: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.strategy_revision, OnlyPrivateAssetRevisionReferenceV1)
            or self.strategy_revision.private_asset_kind is not OnlyPrivateAssetKind.STRATEGY
            or not isinstance(self.research_context, OnlyPrivateStrategyResearchContextV1)
        ):
            raise ValueError("PRIVATE_STRATEGY_REVISION_INVALID")
        if len(self.runtime_generation_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.runtime_generation_fingerprint
        ):
            raise ValueError("RUNTIME_GENERATION_IDENTITY_INVALID")


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
        runtime_generations: _ExactRuntimeGenerations | None = None,
        runtime_definition_resolver: OnlyResearchHostedRuntimeGenerationResolver | None = None,
    ) -> None:
        self._composer = composer
        self._compositions = compositions
        self._definitions = definitions
        self._research = research
        self._authoring_generations = authoring_generations
        self._runtime_generations = runtime_generations
        self._runtime_definition_resolver = runtime_definition_resolver

    def submit(self, request: OnlyPrivateStrategyResearchRequest) -> OnlyPrivateStrategyResearchOutcome:
        composer = self._composer
        # AuthoringExecutionGeneration is a Factor-scoped authority. It is
        # deliberately not accepted as Strategy Research execution context.
        if (self._runtime_generations is None) != (self._runtime_definition_resolver is None):
            raise ValueError("PRIVATE_STRATEGY_RUNTIME_AUTHORITY_INCOMPLETE")
        if self._runtime_generations is None or self._runtime_definition_resolver is None:
            composed = composer.compose(request.strategy_revision, request.research_context)
            specification = self._definitions.resolve(composed.research_definition).specification
        else:
            manifest = self._runtime_generations.require_runtime_generation(request.runtime_generation_fingerprint)
            composed = composer.compose(
                request.strategy_revision,
                request.research_context,
                runtime_manifest=manifest,
            )
            exact = self._runtime_definition_resolver.resolve_definition(
                request.runtime_generation_fingerprint,
                composed.research_definition,
            )
            if (
                exact.research_definition_fingerprint != composed.composition.research_definition_fingerprint
                or exact.specification_fingerprint != exact.specification.specification_fingerprint
            ):
                raise ValueError("PRIVATE_STRATEGY_RUNTIME_DEFINITION_MISMATCH")
            specification = exact.specification
        self._compositions.put(composed.composition, request.research_context)
        submission = self._research.submit_research_run(
            request.submission_key,
            specification,
            runtime_generation_fingerprint=request.runtime_generation_fingerprint,
            strategy_research_composition_fingerprint=composed.composition.composition_fingerprint,
        )
        return OnlyPrivateStrategyResearchOutcome(composed, submission)

    def submit_reference(
        self,
        submission_key: OnlyProductCommandId,
        strategy_revision: OnlyPrivateAssetRevisionReferenceV1,
        research_context: OnlyPrivateStrategyResearchContextV1,
        runtime_generation_fingerprint: str,
    ) -> OnlyPrivateStrategyResearchOutcome:
        return self.submit(
            OnlyPrivateStrategyResearchRequest(
                submission_key,
                strategy_revision,
                research_context,
                runtime_generation_fingerprint,
            )
        )


__all__ = [
    "OnlyPrivateStrategyResearchApplicationService",
    "OnlyPrivateStrategyResearchOutcome",
    "OnlyPrivateStrategyResearchRequest",
]
