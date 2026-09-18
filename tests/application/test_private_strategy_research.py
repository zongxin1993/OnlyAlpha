from __future__ import annotations

from types import SimpleNamespace

from onlyalpha.application.private_strategy_research import (
    OnlyPrivateStrategyResearchApplicationService,
    OnlyPrivateStrategyResearchRequest,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.quant_assets import (
    OnlyInMemoryPrivateStrategyResearchCompositionStore,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateStrategyResearchComposer,
)
from tests.quant_assets.test_private_strategy_composition import _Assets, _case


class _Definitions:
    def __init__(self) -> None:
        self.definition = None

    def resolve(self, definition):  # type: ignore[no-untyped-def]
        self.definition = definition
        return SimpleNamespace(specification=object())


class _Research:
    def __init__(self) -> None:
        self.fingerprint = None

    def submit_research_run(
        self,
        submission_key,
        specification,
        authoring_generation_fingerprint=None,
        *,
        strategy_research_composition_fingerprint=None,
    ):  # type: ignore[no-untyped-def]
        self.fingerprint = strategy_research_composition_fingerprint
        return SimpleNamespace(specification=specification, submission_key=submission_key)


def test_private_strategy_research_application_binds_derived_composition() -> None:
    strategy, factor, context, catalog = _case()
    composer = OnlyPrivateStrategyResearchComposer(_Assets(strategy, factor), catalog)
    definitions = _Definitions()
    research = _Research()
    compositions = OnlyInMemoryPrivateStrategyResearchCompositionStore()
    service = OnlyPrivateStrategyResearchApplicationService(
        composer=composer,
        compositions=compositions,
        definitions=definitions,
        research=research,
    )
    reference = OnlyPrivateAssetRevisionReferenceV1(
        OnlyPrivateAssetKind.STRATEGY,
        strategy.strategy_id,
        strategy.revision_fingerprint,
    )

    outcome = service.submit(
        OnlyPrivateStrategyResearchRequest(
            OnlyProductCommandId("00000000-0000-4000-8000-000000000933"),
            reference,
            context,
        )
    )

    assert definitions.definition == outcome.composition.research_definition
    assert compositions.load(outcome.composition.composition_fingerprint) == outcome.composition.composition
    assert research.fingerprint == outcome.composition.composition_fingerprint
