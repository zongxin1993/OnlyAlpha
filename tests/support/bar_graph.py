"""Explicit Bar dependency graphs shared by runtime tests."""

from onlyalpha.domain.market import OnlyBarType
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionRecipe,
    OnlyBarDependencyGraph,
    OnlyBarDerivedDependency,
)


def only_native_bar_graph(*bar_types: OnlyBarType) -> OnlyBarDependencyGraph:
    return OnlyBarDependencyGraph(bar_types, ())


def only_time_bar_graph(source: OnlyBarType, *targets: OnlyBarType) -> OnlyBarDependencyGraph:
    return OnlyBarDependencyGraph(
        (source,),
        tuple(
            OnlyBarDerivedDependency(
                source,
                target,
                OnlyBarConstructionRecipe.derived(target.semantic, source.semantic, algorithm_id="TIME_BAR"),
            )
            for target in targets
        ),
    )
