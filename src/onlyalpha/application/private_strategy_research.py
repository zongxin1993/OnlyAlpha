"""Application boundary for researching one exact Private Strategy Revision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
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
from onlyalpha.research.specification.model import OnlyResearchSpecification


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
    ) -> None:
        self._composer = composer
        self._compositions = compositions
        self._definitions = definitions
        self._research = research

    def submit(self, request: OnlyPrivateStrategyResearchRequest) -> OnlyPrivateStrategyResearchOutcome:
        composed = self._composer.compose(request.strategy_revision, request.research_context)
        resolved = self._definitions.resolve(composed.research_definition)
        self._compositions.put(composed.composition, request.research_context)
        submission = self._research.submit_research_run(
            request.submission_key,
            resolved.specification,
            request.authoring_generation_fingerprint,
            strategy_research_composition_fingerprint=composed.composition.composition_fingerprint,
        )
        return OnlyPrivateStrategyResearchOutcome(composed, submission)


__all__ = [
    "OnlyPrivateStrategyResearchApplicationService",
    "OnlyPrivateStrategyResearchOutcome",
    "OnlyPrivateStrategyResearchRequest",
]
