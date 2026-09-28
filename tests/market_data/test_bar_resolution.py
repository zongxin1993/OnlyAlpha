from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.errors import OnlySerializationError
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import (
    OnlyBarAlignment,
    OnlyBarSemantic,
    OnlyBarType,
    OnlyCalendarPeriodBarFormation,
    OnlyCalendarPeriodUnit,
)
from onlyalpha.market_data.resolution import (
    OnlyBarCapability,
    OnlyBarConstructionAlgorithmRegistry,
    OnlyBarConstructionIdentity,
    OnlyBarConstructionRecipe,
    OnlyBarConstructionRequirement,
    OnlyBarConstructionRequirementKind,
    OnlyBarDependencyGraph,
    OnlyBarDerivedDependency,
    OnlyBarResolutionMode,
    OnlyBarResolutionPlan,
    OnlyBarResolutionPolicy,
    only_expected_fixed_duration_bar_ends,
    only_plan_bar_resolution,
)
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.strategy.revision import OnlyStrategyMarketInputContract

INSTRUMENT = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
REVISION = "a" * 64
CALENDAR = "calendar:v1"


def semantic(window: int, stride: int | None = None) -> OnlyBarSemantic:
    return OnlyBarSemantic.fixed_duration(window, stride, alignment=OnlyBarAlignment.UTC)


def capability(value: OnlyBarSemantic) -> OnlyBarCapability:
    return OnlyBarCapability(value, True, True, CALENDAR, 0)


def plan(
    target: OnlyBarSemantic,
    capabilities: tuple[OnlyBarCapability, ...],
    requirement: OnlyBarConstructionRequirement | None = None,
) -> OnlyBarResolutionPlan:
    return only_plan_bar_resolution(
        target,
        capabilities,
        calendar_fingerprint=CALENDAR,
        source_id="binance.spot.live",
        instrument_id=str(INSTRUMENT),
        integration_revision_fingerprint=REVISION,
        requirement=requirement,
    )


def test_same_semantic_has_distinct_native_and_derived_construction() -> None:
    target = semantic(15)
    native_plan = plan(target, (capability(target), capability(semantic(1))))
    derived_recipe = OnlyBarConstructionRecipe.derived(target, semantic(1), algorithm_id="TIME_BAR")
    derived_plan = plan(
        target,
        (capability(target), capability(semantic(1))),
        OnlyBarConstructionRequirement.exact(derived_recipe),
    )

    assert OnlyBarType(INSTRUMENT, target) == OnlyBarType(INSTRUMENT, target)
    assert native_plan.mode is OnlyBarResolutionMode.PROVIDER_NATIVE
    assert derived_plan.mode is OnlyBarResolutionMode.DERIVED
    native = OnlyBarConstructionIdentity.build(native_plan, data_version="v1")
    derived = OnlyBarConstructionIdentity.build(
        derived_plan,
        data_version="v1",
        base_revision_id="revision:1",
        base_revision_fingerprint="b" * 64,
        base_seal_id="seal:1",
    )
    assert native.fingerprint != derived.fingerprint


def test_capability_evolution_does_not_change_exact_strategy_recipe() -> None:
    target = semantic(15)
    recipe = OnlyBarConstructionRecipe.derived(target, semantic(1), algorithm_id="TIME_BAR")
    requirement = OnlyBarConstructionRequirement.exact(recipe)
    before = plan(target, (capability(semantic(1)),), requirement)
    after = plan(target, (capability(semantic(1)), capability(target)), requirement)
    interactive = plan(target, (capability(semantic(1)), capability(target)))

    assert before.resolved_recipe == after.resolved_recipe == recipe
    assert after.mode is OnlyBarResolutionMode.DERIVED
    assert interactive.mode is OnlyBarResolutionMode.PROVIDER_NATIVE


def test_research_to_live_exact_recipe_is_invariant_after_native_capability_appears() -> None:
    target = semantic(15)
    research_recipe = OnlyBarConstructionRecipe.derived(target, semantic(1), algorithm_id="TIME_BAR")
    frozen = OnlyStrategyMarketInputContract(target, OnlyBarConstructionRequirement.exact(research_recipe))
    evolved = (capability(semantic(1)), capability(target))

    runtime_recipes = tuple(
        plan(target, evolved, frozen.construction_requirement).resolved_recipe
        for _runtime in ("BACKTEST", "SIM", "LIVE")
    )

    assert runtime_recipes == (research_recipe, research_recipe, research_recipe)


def test_runtime_dependency_graph_is_explicit() -> None:
    one, seven, fifteen = semantic(1), semantic(7), semantic(15)
    source = OnlyBarType(INSTRUMENT, one)
    target = OnlyBarType(INSTRUMENT, seven)
    recipe = OnlyBarConstructionRecipe.derived(seven, one, algorithm_id="TIME_BAR")
    graph = OnlyBarDependencyGraph(
        (source, OnlyBarType(INSTRUMENT, fifteen)),
        (OnlyBarDerivedDependency(source, target, recipe),),
    )

    assert graph.provider_inputs == (source, OnlyBarType(INSTRUMENT, fifteen))
    assert graph.derived_dependencies[0].target == target


def test_runtime_dependency_graph_rejects_an_unprovided_source() -> None:
    source = OnlyBarType(INSTRUMENT, semantic(1))
    target = OnlyBarType(INSTRUMENT, semantic(7))
    with pytest.raises(ValueError, match="BAR_DEPENDENCY_GRAPH_INVALID"):
        OnlyBarDependencyGraph(
            (),
            (
                OnlyBarDerivedDependency(
                    source,
                    target,
                    OnlyBarConstructionRecipe.derived(target.semantic, source.semantic, algorithm_id="TIME_BAR"),
                ),
            ),
        )


def test_rolling_recipe_is_fingerprintable_but_executor_fails_closed() -> None:
    rolling = semantic(15, 1)
    recipe = OnlyBarConstructionRecipe.derived(rolling, semantic(1), algorithm_id="ROLLING_TIME_BAR")
    requirement = OnlyBarConstructionRequirement.exact(recipe)
    resolved = plan(rolling, (capability(semantic(1)),), requirement)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    definition = OnlyResearchDatasetDefinition((INSTRUMENT,), rolling, OnlyTimeRange(start, start + timedelta(hours=1)))
    strategy_input = OnlyStrategyMarketInputContract(rolling, requirement)

    assert OnlyBarConstructionRecipe.from_dict(recipe.to_dict()) == recipe
    assert OnlyBarConstructionRequirement.from_dict(requirement.to_dict()) == requirement
    assert OnlyResearchDatasetDefinition.from_dict(definition.to_dict()) == definition
    assert OnlyStrategyMarketInputContract.from_dict(strategy_input.to_dict()) == strategy_input
    assert resolved.resolved_recipe == recipe
    with pytest.raises(ValueError, match="CONSTRUCTION_ALGORITHM_UNAVAILABLE"):
        OnlyBarConstructionAlgorithmRegistry().require(recipe)


def test_construction_requirement_rejects_policy_and_recipe_together() -> None:
    target = semantic(15)
    with pytest.raises(ValueError, match="BAR_CONSTRUCTION_REQUIREMENT_INVALID"):
        OnlyBarConstructionRequirement(
            OnlyBarConstructionRequirementKind.POLICY,
            OnlyBarResolutionPolicy.PREFER_EXACT_NATIVE,
            OnlyBarConstructionRecipe.provider_native(target),
        )


def test_semantic_variants_and_plan_persistence_are_versioned() -> None:
    calendar = OnlyBarSemantic(OnlyCalendarPeriodBarFormation(OnlyCalendarPeriodUnit.DAY))
    assert OnlyBarSemantic.from_dict(calendar.to_dict()) == calendar
    resolved = plan(semantic(15), (capability(semantic(15)),))
    assert OnlyBarResolutionPlan.from_dict(resolved.to_dict()) == resolved
    with pytest.raises(ValueError, match="REBUILD_REQUIRED"):
        OnlyBarResolutionPlan.from_dict({"schema_version": 2})
    with pytest.raises(ValueError, match="REBUILD_REQUIRED"):
        OnlyBarConstructionIdentity.from_dict({"schema_version": 1})
    old_bar_type = OnlyBarType(INSTRUMENT, semantic(1)).to_dict()
    old_bar_type["schema_version"] = 1
    with pytest.raises(OnlySerializationError, match="schema version"):
        OnlyBarType.from_dict(old_bar_type)


def test_fixed_duration_output_grid_uses_window_and_stride() -> None:
    minute = 60_000_000_000
    assert only_expected_fixed_duration_bar_ends(semantic(15, 5), start_ns=0, end_ns=30 * minute, grid_origin_ns=0) == (
        15 * minute,
        20 * minute,
        25 * minute,
        30 * minute,
    )
