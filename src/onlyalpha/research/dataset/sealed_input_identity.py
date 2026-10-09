"""Pure sealed-input plan and identity; no materialization or source access."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.market_data.durable.models import OnlyMarketDataScope
from onlyalpha.market_data.resolution import OnlyBarConstructionIdentity

from .definition import OnlyResearchDatasetDefinition
from .validation import OnlyResearchDatasetError


@dataclass(frozen=True, slots=True)
class OnlySealedMarketDataMaterializationPlan:
    revision_ids: tuple[str, ...]
    definition: OnlyResearchDatasetDefinition
    scopes: tuple[OnlyMarketDataScope, ...]
    constructions: tuple[OnlyBarConstructionIdentity, ...] = ()
    calendars: tuple[OnlyTradingCalendar | None, ...] = ()

    def __post_init__(self) -> None:
        if (
            len(self.revision_ids) != len(self.scopes)
            or any(not item.strip() for item in self.revision_ids)
            or len(self.scopes) != len(self.definition.instruments)
        ):
            raise ValueError("DATASET_MARKET_DATA_REVISION_INPUT_INVALID")
        if tuple(sorted(scope.instrument_id for scope in self.scopes)) != tuple(
            sorted(str(item) for item in self.definition.instruments)
        ):
            raise ValueError("DATASET_MARKET_DATA_SCOPE_MISMATCH")
        if any(scope.data_kind != "BAR" for scope in self.scopes):
            raise ValueError("DATASET_MARKET_DATA_KIND_UNSUPPORTED")
        if not self.constructions:
            if any(scope.bar_construction is None for scope in self.scopes):
                raise ValueError("DATASET_BAR_CONSTRUCTION_UNPROVABLE")
            object.__setattr__(self, "constructions", tuple(scope.bar_construction for scope in self.scopes))
        if len(self.constructions) != len(self.scopes):
            raise ValueError("DATASET_BAR_CONSTRUCTION_INVALID")
        if not self.calendars:
            object.__setattr__(self, "calendars", (None,) * len(self.scopes))
        if len(self.calendars) != len(self.scopes):
            raise ValueError("DATASET_BAR_CALENDAR_INVALID")


def only_sealed_market_data_input_fingerprints(
    plan: OnlySealedMarketDataMaterializationPlan,
    construction_bindings: tuple[tuple[str, str, str, str], ...],
) -> tuple[str, str]:
    """Canonical input identities shared by production and lineage verification."""
    bindings = tuple(
        sorted(
            zip(plan.scopes, plan.revision_ids, plan.constructions, plan.calendars, strict=True),
            key=lambda item: item[0].instrument_id,
        )
    )
    ordered = tuple(sorted(construction_bindings, key=lambda item: item[0]))
    if tuple((item[0], item[1]) for item in ordered) != tuple(
        (scope.instrument_id, construction.fingerprint) for scope, _, construction, _ in bindings
    ):
        raise OnlyResearchDatasetError("DATASET_BAR_CONSTRUCTION_MISMATCH")
    return only_canonical_fingerprint(ordered), only_canonical_fingerprint(
        {
            "definition": plan.definition,
            "scopes": tuple(scope for scope, _, _, _ in bindings),
            "constructions": tuple(item.fingerprint for _, _, item, _ in bindings),
        }
    )
