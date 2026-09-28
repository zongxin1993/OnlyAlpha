"""Immutable strategy Bar subscriptions and primary-period selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from onlyalpha.domain.market import OnlyBarType, OnlyFixedDurationBarFormation
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionRecipe,
    OnlyBarDependencyGraph,
    OnlyBarDerivedDependency,
)


class OnlyBarDeliveryMode(StrEnum):
    PRIMARY_ONLY = "PRIMARY_ONLY"
    EACH_BAR = "EACH_BAR"
    TIME_SLICE = "TIME_SLICE"


class OnlyBarFreshnessPolicy(StrEnum):
    LATEST_CLOSED = "LATEST_CLOSED"
    SAME_EVENT_TIME = "SAME_EVENT_TIME"


class OnlyIncompleteBarPolicy(StrEnum):
    DROP = "DROP"
    EMIT_PARTIAL = "EMIT_PARTIAL"
    TRUNCATE_AT_SESSION_END = "TRUNCATE_AT_SESSION_END"
    REJECT = "REJECT"


class OnlyMissingBarPolicy(StrEnum):
    REJECT = "REJECT"
    SKIP_WINDOW = "SKIP_WINDOW"
    EMIT_PARTIAL = "EMIT_PARTIAL"
    INSERT_EMPTY = "INSERT_EMPTY"
    FILL_FORWARD = "FILL_FORWARD"


class OnlyMarketDataSequencePolicy(StrEnum):
    REJECT = "REJECT"
    IGNORE_EXACT_DUPLICATE = "IGNORE_EXACT_DUPLICATE"


class OnlyLateDataPolicy(StrEnum):
    REJECT = "REJECT"


class OnlyBarRevisionPolicy(StrEnum):
    REJECT = "REJECT"


@dataclass(frozen=True, order=True, slots=True)
class OnlyBarSubscriptionId:
    value: UUID

    @classmethod
    def new(cls) -> OnlyBarSubscriptionId:
        return cls(uuid4())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class OnlyBarSubscription:
    """One Cluster's immutable set of Bar requirements."""

    bar_types: tuple[OnlyBarType, ...]
    dependency_graph: OnlyBarDependencyGraph
    primary_bar_type: OnlyBarType | None = None
    delivery_mode: OnlyBarDeliveryMode = OnlyBarDeliveryMode.PRIMARY_ONLY
    freshness_policy: OnlyBarFreshnessPolicy = OnlyBarFreshnessPolicy.LATEST_CLOSED
    subscription_id: OnlyBarSubscriptionId = field(default_factory=OnlyBarSubscriptionId.new)

    def __post_init__(self) -> None:
        unique = tuple(dict.fromkeys(self.bar_types))
        if not unique:
            raise ValueError("Bar subscription requires at least one BarType")
        if len(unique) != len(self.bar_types):
            raise ValueError("Bar subscription cannot contain duplicate BarTypes")
        if len({item.instrument_id for item in unique}) != 1:
            raise ValueError("first-phase Bar subscription supports one instrument")
        graph_nodes = set(self.dependency_graph.provider_inputs)
        graph_nodes.update(item.target for item in self.dependency_graph.derived_dependencies)
        if graph_nodes != set(unique):
            raise ValueError("Bar subscription must exactly match its dependency graph")
        if self.delivery_mode is not OnlyBarDeliveryMode.PRIMARY_ONLY:
            raise ValueError("first-phase dispatcher only supports PRIMARY_ONLY")
        primary = self.primary_bar_type
        if primary is None:
            if any(not isinstance(item.semantic.formation, OnlyFixedDurationBarFormation) for item in unique):
                raise ValueError("non-time Bar subscriptions require explicit primary_bar_type")
            primary = min(unique, key=lambda item: (item.semantic.stride_minutes, only_bar_type_id(item)))
        if primary not in unique:
            raise ValueError("primary_bar_type must be included in bar_types")
        object.__setattr__(self, "bar_types", unique)
        object.__setattr__(self, "primary_bar_type", primary)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "subscription_id": str(self.subscription_id),
            "bar_types": [item.to_dict() for item in self.bar_types],
            "dependency_graph": {
                "provider_inputs": [item.to_dict() for item in self.dependency_graph.provider_inputs],
                "derived_dependencies": [
                    {
                        "source": item.source.to_dict(),
                        "target": item.target.to_dict(),
                        "recipe": item.recipe.to_dict(),
                    }
                    for item in self.dependency_graph.derived_dependencies
                ],
            },
            "primary_bar_type": self.primary_bar_type.to_dict(),  # type: ignore[union-attr]
            "delivery_mode": self.delivery_mode.value,
            "freshness_policy": self.freshness_policy.value,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> OnlyBarSubscription:
        if payload.get("schema_version") != 2:
            raise ValueError("BAR_SUBSCRIPTION_REBUILD_REQUIRED")
        raw_bar_types = payload["bar_types"]
        if not isinstance(raw_bar_types, list):
            raise ValueError("bar_types must be a list")
        primary_payload = payload["primary_bar_type"]
        if not isinstance(primary_payload, dict):
            raise ValueError("primary_bar_type must be a mapping")
        graph_payload = payload.get("dependency_graph")
        if not isinstance(graph_payload, dict):
            raise ValueError("BAR_SUBSCRIPTION_REBUILD_REQUIRED")
        provider_inputs = graph_payload.get("provider_inputs")
        dependencies = graph_payload.get("derived_dependencies")
        if not isinstance(provider_inputs, list) or not isinstance(dependencies, list):
            raise ValueError("BAR_SUBSCRIPTION_REBUILD_REQUIRED")
        if any(not isinstance(item, dict) for item in (*raw_bar_types, *provider_inputs)) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("source"), dict)
            or not isinstance(item.get("target"), dict)
            or not isinstance(item.get("recipe"), dict)
            for item in dependencies
        ):
            raise ValueError("BAR_SUBSCRIPTION_INVALID")
        bar_type_payloads = tuple(cast(dict[str, object], item) for item in raw_bar_types)
        provider_payloads = tuple(cast(dict[str, object], item) for item in provider_inputs)
        dependency_payloads = tuple(cast(dict[str, object], item) for item in dependencies)
        graph = OnlyBarDependencyGraph(
            tuple(OnlyBarType.from_dict(item) for item in provider_payloads),
            tuple(
                OnlyBarDerivedDependency(
                    OnlyBarType.from_dict(cast(dict[str, object], item["source"])),
                    OnlyBarType.from_dict(cast(dict[str, object], item["target"])),
                    OnlyBarConstructionRecipe.from_dict(cast(dict[str, object], item["recipe"])),
                )
                for item in dependency_payloads
            ),
        )
        result = cls(
            tuple(OnlyBarType.from_dict(item) for item in bar_type_payloads),
            graph,
            OnlyBarType.from_dict(primary_payload),
            OnlyBarDeliveryMode(str(payload["delivery_mode"])),
            OnlyBarFreshnessPolicy(str(payload["freshness_policy"])),
            OnlyBarSubscriptionId(UUID(str(payload["subscription_id"]))),
        )
        if result.to_dict() != payload:
            raise ValueError("BAR_SUBSCRIPTION_INVALID")
        return result


@dataclass(frozen=True, slots=True)
class OnlyBarSubscriptionSet:
    subscriptions: tuple[OnlyBarSubscription, ...]

    def __post_init__(self) -> None:
        ids = [item.subscription_id for item in self.subscriptions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate Bar subscription ID")


def only_bar_type_id(bar_type: OnlyBarType) -> str:
    """Stable identifier used for sorting and replay DTOs."""
    return bar_type.to_json()
