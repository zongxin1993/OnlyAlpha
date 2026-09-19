from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from onlyalpha_plugin_targets.registration import FORWARD_RETURN

from onlyalpha.calculation import OnlyCalculationDataType, OnlyCalculationKind, OnlyCalculationTypeReference
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSpecification
from onlyalpha.quant_assets import (
    OnlyInMemoryPrivateStrategyResearchCompositionStore,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateFactorSnapshotProviderSource,
    OnlyPrivateStrategyDefinitionV1,
    OnlyPrivateStrategyDraft,
    OnlyPrivateStrategyFactorRevisionDependencyV1,
    OnlyPrivateStrategyResearchComposer,
    OnlyPrivateStrategyResearchCompositionError,
    OnlyPrivateStrategyResearchCompositionVerifier,
    OnlyPrivateStrategyResearchContextV1,
    OnlyPrivateStrategyRevision,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)
from onlyalpha.research.definition import (
    OnlyResearchCalculationInput,
    OnlyResearchCalculationInstance,
    OnlyResearchComparison,
    OnlyResearchComparisonOperator,
    OnlyResearchFixedParameter,
    OnlyResearchSignals,
    OnlyResearchStatisticsRequest,
    OnlyResearchTypedLiteral,
    OnlyResearchVariableRef,
)
from onlyalpha.research.evaluation.definition import OnlyResearchStatisticsDefinition, OnlyResearchStatisticsMethod
from onlyalpha.strategy.revision import OnlyStrategyMarketInputContract, OnlyStrategyUniverse
from tests.quant_assets.test_private_asset_contract_conformance import _closure


class _Assets:
    def __init__(self, strategy: OnlyPrivateStrategyRevision, factor) -> None:
        self.strategy = strategy
        self.factor = factor

    def load_strategy_revision(self, strategy_id: str, revision_fingerprint: str):
        assert (strategy_id, revision_fingerprint) == (
            self.strategy.strategy_id,
            self.strategy.revision_fingerprint,
        )
        return self.strategy

    def load_factor_revision(self, factor_id: str, revision_fingerprint: str):
        assert (factor_id, revision_fingerprint) == (self.factor.factor_id, self.factor.revision_fingerprint)
        return self.factor


def _case():
    closure = _closure()
    factor = closure.revision
    calculation = OnlyResearchCalculationInstance(
        "momentum",
        OnlyCalculationTypeReference(OnlyCalculationKind.FACTOR, factor.factor_id, factor.semantic_version),
        {"offset": OnlyResearchFixedParameter(Decimal("1"))},
        ("value",),
        (OnlyResearchCalculationInput("close", "bar.close"),),
    )
    signal = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchVariableRef("momentum", "value"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("0")),
    )
    definition = OnlyPrivateStrategyDefinitionV1(
        1,
        OnlyStrategyUniverse((OnlyInstrumentId.parse("TEST.XSHG"),)),
        OnlyStrategyMarketInputContract(
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
            OnlyAdjustmentType.RAW,
        ),
        (calculation,),
        (OnlyPrivateStrategyFactorRevisionDependencyV1(factor.factor_id, factor.revision_fingerprint),),
        signal,
        OnlyResearchSignals(signal, signal),
    )
    strategy = OnlyPrivateStrategyRevision.from_draft(
        OnlyPrivateStrategyDraft("private.strategy.composition", "1", definition.to_dict())
    )
    target = OnlyResearchCalculationInstance(
        "forward_return",
        OnlyCalculationTypeReference(OnlyCalculationKind.TARGET, FORWARD_RETURN.type_id, "1"),
        {"exit_offset": OnlyResearchFixedParameter(1)},
        ("target_value",),
        (
            OnlyResearchCalculationInput("entry_price", "bar.close"),
            OnlyResearchCalculationInput("exit_price", "bar.close"),
        ),
    )
    context = OnlyPrivateStrategyResearchContextV1(
        "2026-01-01T00:00:00+00:00",
        "2026-02-01T00:00:00+00:00",
        (target,),
        (
            OnlyResearchStatisticsRequest(
                OnlyResearchVariableRef("momentum", "value"),
                "forward_return",
                OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC),
            ),
        ),
    )
    provider = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            "private.factor.composition.provider",
            factor.revision_fingerprint,
            OnlyQuantAssetKind.FACTOR,
            OnlyPrivateFactorSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
        ),
        closure.registrations,
        closure.provider_snapshot,
    )
    return strategy, factor, context, OnlyQuantAssetCatalogGeneration((provider,))


def test_private_strategy_composer_is_exact_and_deterministic() -> None:
    strategy, factor, context, catalog = _case()
    composer = OnlyPrivateStrategyResearchComposer(_Assets(strategy, factor), catalog)
    reference = OnlyPrivateAssetRevisionReferenceV1(
        OnlyPrivateAssetKind.STRATEGY, strategy.strategy_id, strategy.revision_fingerprint
    )

    first = composer.compose(reference, context)
    second = composer.compose(reference, context)

    assert first.composition == second.composition
    assert first.research_definition == second.research_definition
    assert first.research_definition.definition_fingerprint == first.composition.research_definition_fingerprint

    changed_context = OnlyPrivateStrategyResearchContextV1(
        "2026-02-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00", context.targets, context.statistics
    )
    changed = composer.compose(reference, changed_context)
    assert changed.research_definition.definition_fingerprint != first.research_definition.definition_fingerprint
    assert changed.composition.composition_fingerprint != first.composition.composition_fingerprint
    assert strategy.revision_fingerprint == first.composition.private_strategy_revision_fingerprint


def test_private_strategy_composition_rejects_admission_generation_drift() -> None:
    strategy, factor, context, catalog = _case()
    composer = OnlyPrivateStrategyResearchComposer(_Assets(strategy, factor), catalog)
    reference = OnlyPrivateAssetRevisionReferenceV1(
        OnlyPrivateAssetKind.STRATEGY, strategy.strategy_id, strategy.revision_fingerprint
    )
    composed = composer.compose(reference, context)
    store = OnlyInMemoryPrivateStrategyResearchCompositionStore()
    store.put(composed.composition, context)
    admitted_catalog = OnlyQuantAssetCatalogGeneration(())

    class _Generation:
        def require_work_binding(self, _work_id: str) -> object:
            return SimpleNamespace(runtime_generation_fingerprint="b" * 64)

        def require_runtime_generation(self, _fingerprint: str) -> object:
            return SimpleNamespace(catalog_generation_fingerprint=admitted_catalog.generation_fingerprint)

    verifier = OnlyPrivateStrategyResearchCompositionVerifier(
        composer,
        store,
        execution_evidence=SimpleNamespace(),  # type: ignore[arg-type]
        runtime_generations=_Generation(),  # type: ignore[arg-type]
        runtime_definition_resolver=SimpleNamespace(),  # type: ignore[arg-type]
    )

    with pytest.raises(
        OnlyPrivateStrategyResearchCompositionError, match="Composition Catalog differs from Runtime Catalog"
    ):
        verifier.verify(
            SimpleNamespace(
                strategy_research_composition_fingerprint=composed.composition_fingerprint,
                run_id=SimpleNamespace(value="run"),
            )
        )


def test_private_strategy_definition_rejects_unknown_and_sweep_fields() -> None:
    strategy, _, _, _ = _case()
    raw = dict(strategy.definition)
    raw["unknown"] = True
    with pytest.raises(ValueError):
        OnlyPrivateStrategyDefinitionV1.from_dict(raw)

    calculation = dict(strategy.definition["calculations"][0])  # type: ignore[index]
    calculation["parameters"] = {
        "offset": {"kind": "SWEEP", "values": [{"type": "DECIMAL", "value": "1"}, {"type": "DECIMAL", "value": "2"}]}
    }
    changed = dict(strategy.definition)
    changed["calculations"] = [calculation]
    with pytest.raises(ValueError):
        OnlyPrivateStrategyDefinitionV1.from_dict(changed)
