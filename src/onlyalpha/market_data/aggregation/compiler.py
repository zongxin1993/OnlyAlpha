"""Canonical compilation of a construction graph into lane-aware runtime routing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.market_data.aggregation.base import OnlyMarketDataConstructionExecutor
from onlyalpha.market_data.resolution import (
    OnlyMarketDataConstructionEdge,
    OnlyMarketDataConstructionGraph,
    OnlyMarketDataConstructionLane,
    OnlyMarketDataInputType,
)


@dataclass(frozen=True, slots=True)
class OnlyProviderInputLane:
    input_type: OnlyMarketDataInputType
    source_binding_identity: str

    @property
    def lane_id(self) -> str:
        return only_canonical_fingerprint(
            {
                "schema_version": 1,
                "kind": "PROVIDER_INPUT",
                "input_type": self.input_type.to_dict(),
                "source_binding_identity": self.source_binding_identity,
            }
        )


@dataclass(frozen=True, slots=True)
class OnlyCompiledConstructionLane:
    lane_id: str
    source_lane_id: str
    topological_level: int
    edge: OnlyMarketDataConstructionEdge
    executor: OnlyMarketDataConstructionExecutor


@dataclass(frozen=True, slots=True)
class OnlyCompiledConstructionPlan:
    graph_fingerprint: str
    provider_input_lanes: tuple[OnlyProviderInputLane, ...]
    construction_lanes: tuple[OnlyCompiledConstructionLane, ...]
    topological_levels: tuple[tuple[str, ...], ...]
    outgoing_by_lane: Mapping[str, tuple[OnlyCompiledConstructionLane, ...]]
    lane_by_id: Mapping[str, OnlyProviderInputLane | OnlyCompiledConstructionLane]


class OnlyConstructionGraphCompiler:
    def __init__(self, source_binding_identity: str) -> None:
        if not source_binding_identity.strip():
            raise ValueError("CONSTRUCTION_SOURCE_BINDING_INVALID")
        self._source_binding_identity = source_binding_identity

    def compile(
        self,
        graph: OnlyMarketDataConstructionGraph,
        executors: Mapping[str, OnlyMarketDataConstructionExecutor],
    ) -> OnlyCompiledConstructionPlan:
        providers = tuple(
            OnlyProviderInputLane(item, self._source_binding_identity)
            for item in sorted(graph.provider_inputs, key=lambda item: only_canonical_json(item.to_dict()))
        )
        source_lane_ids = {lane.input_type: lane.lane_id for lane in providers}
        edges_by_target: dict[OnlyMarketDataInputType, OnlyMarketDataConstructionEdge] = {
            edge.target: edge for edge in graph.derived_dependencies
        }

        def lane_id(edge: OnlyMarketDataConstructionEdge) -> str:
            return OnlyMarketDataConstructionLane(
                edge.target, edge.recipe.fingerprint, self._source_binding_identity
            ).lane_id

        levels: dict[OnlyMarketDataInputType, int] = {lane.input_type: 0 for lane in providers}

        def level(input_type: OnlyMarketDataInputType) -> int:
            known = levels.get(input_type)
            if known is not None:
                return known
            edge = edges_by_target[input_type]
            value = level(edge.source) + 1
            levels[input_type] = value
            return value

        compiled: list[OnlyCompiledConstructionLane] = []
        for edge in graph.derived_dependencies:
            current_lane_id = lane_id(edge)
            source_lane_id = source_lane_ids.get(edge.source)
            if source_lane_id is None:
                source_lane_id = lane_id(edges_by_target[edge.source])
            executor = executors.get(current_lane_id)
            if executor is None:
                raise ValueError("CONSTRUCTION_EXECUTOR_UNAVAILABLE")
            compiled.append(
                OnlyCompiledConstructionLane(current_lane_id, source_lane_id, level(edge.target), edge, executor)
            )
        ordered = tuple(sorted(compiled, key=lambda item: (item.topological_level, item.lane_id)))
        outgoing: dict[str, list[OnlyCompiledConstructionLane]] = {}
        for lane in ordered:
            outgoing.setdefault(lane.source_lane_id, []).append(lane)
        max_level = max((lane.topological_level for lane in ordered), default=0)
        by_id: dict[str, OnlyProviderInputLane | OnlyCompiledConstructionLane] = {
            lane.lane_id: lane for lane in providers
        }
        by_id.update({lane.lane_id: lane for lane in ordered})
        return OnlyCompiledConstructionPlan(
            graph.fingerprint,
            providers,
            ordered,
            (
                tuple(lane.lane_id for lane in providers),
                *(
                    tuple(lane.lane_id for lane in ordered if lane.topological_level == current)
                    for current in range(1, max_level + 1)
                ),
            ),
            MappingProxyType({key: tuple(value) for key, value in outgoing.items()}),
            MappingProxyType(by_id),
        )
