"""Immutable Dataset materialization from one exact sealed Market Data Revision."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.market_data.aggregation.time_bar import OnlyBarAggregationError, OnlyTimeBarAggregator
from onlyalpha.market_data.durable.models import OnlyMarketDataScope
from onlyalpha.market_data.durable.revision import OnlyHistoricalMarketDataQueryService
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionAlgorithmRegistry,
    OnlyBarConstructionIdentity,
    OnlyBarResolutionMode,
)
from onlyalpha.market_data.subscriptions import OnlyIncompleteBarPolicy, OnlyMissingBarPolicy

from .definition import OnlyResearchDatasetDefinition
from .identity import only_canonical_bars, only_content_fingerprint, only_snapshot_fingerprint
from .lineage import (
    OnlyDatasetMaterialization,
    OnlyDatasetMaterializationStore,
    OnlyMarketDataRevisionBinding,
    only_dataset_materialization_id,
)
from .manifest import OnlyResearchDatasetProvenance, OnlyResearchDatasetSnapshot
from .ports import OnlyResearchDatasetSnapshotStore
from .schema import RESEARCH_BAR_DATASET_SCHEMA_V2
from .validation import OnlyResearchDatasetError, only_validate_dataset_bars


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


@dataclass(frozen=True, slots=True)
class OnlySealedMarketDataMaterializationResult:
    snapshot: OnlyResearchDatasetSnapshot
    materialization: OnlyDatasetMaterialization


class OnlySealedMarketDataDatasetMaterializer:
    def __init__(
        self,
        query: OnlyHistoricalMarketDataQueryService,
        store: OnlyResearchDatasetSnapshotStore,
        materialization_store: OnlyDatasetMaterializationStore,
        audit_time: Callable[[], datetime],
    ) -> None:
        self._query = query
        self._store = store
        self._materialization_store = materialization_store
        self._audit_time = audit_time

    def materialize(self, plan: OnlySealedMarketDataMaterializationPlan) -> OnlyResearchDatasetSnapshot:
        return self.materialize_with_lineage(plan).snapshot

    def materialize_with_lineage(
        self, plan: OnlySealedMarketDataMaterializationPlan
    ) -> OnlySealedMarketDataMaterializationResult:
        bars = []
        provenance = []
        revision_bindings = []
        construction_bindings = []
        bindings = tuple(
            sorted(
                zip(plan.scopes, plan.revision_ids, plan.constructions, plan.calendars, strict=True),
                key=lambda item: item[0].instrument_id,
            )
        )
        for scope, revision_id, construction, calendar in bindings:
            revision, seal = self._query.resolve_with_seal(revision_id)
            if (
                revision.scope != scope
                or construction.plan.instrument_id != scope.instrument_id
                or construction.plan.source_id != scope.source_id
                or construction.data_version != scope.data_version
            ):
                raise OnlyResearchDatasetError("DATASET_MARKET_DATA_SCOPE_MISMATCH")
            if construction.plan.target_semantic != plan.definition.bar_semantic:
                raise OnlyResearchDatasetError("DATASET_BAR_CONSTRUCTION_MISMATCH")
            if construction.plan.mode is OnlyBarResolutionMode.PROVIDER_NATIVE:
                if construction != scope.bar_construction:
                    raise OnlyResearchDatasetError("DATASET_BAR_CONSTRUCTION_MISMATCH")
            elif (
                construction.base_revision_id != revision_id
                or construction.base_revision_fingerprint != revision.fingerprint
                or construction.base_seal_id != seal.seal_id
                or scope.bar_construction is None
                or scope.bar_construction.plan.target_semantic != construction.plan.base_semantic
                or construction.plan.alignment_id != scope.bar_construction.plan.alignment_id
                or construction.plan.integration_revision_fingerprint
                != scope.bar_construction.plan.integration_revision_fingerprint
                or calendar is None
                or only_canonical_fingerprint(calendar.to_dict()) != construction.plan.alignment_id
            ):
                raise OnlyResearchDatasetError("DATASET_DERIVED_BASE_UNPROVABLE")
            facts = self._query.read_exact(revision_id, scope)
            instrument_bars = []
            for fact in facts:
                update = OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload)
                if not isinstance(update.payload, OnlyBarUpdate):
                    raise OnlyResearchDatasetError("DATASET_MARKET_DATA_FACT_KIND_INVALID")
                instrument_bars.append(update.payload.bar)
            if construction.plan.mode is OnlyBarResolutionMode.DERIVED:
                assert calendar is not None
                recipe = construction.plan.resolved_recipe
                OnlyBarConstructionAlgorithmRegistry().require(recipe)
                assert recipe.incomplete_policy is not None
                assert recipe.missing_policy is not None
                source_type = instrument_bars[0].bar_type if instrument_bars else None
                if source_type is None:
                    raise OnlyResearchDatasetError("DATASET_DERIVED_BASE_UNPROVABLE")
                aggregator = OnlyTimeBarAggregator(
                    source_type,
                    OnlyBarType(source_type.instrument_id, plan.definition.bar_semantic),
                    calendar,
                    OnlyBacktestClock(plan.definition.time_range.end),
                    incomplete_policy=OnlyIncompleteBarPolicy(recipe.incomplete_policy.value),
                    missing_policy=OnlyMissingBarPolicy(recipe.missing_policy.value),
                )
                try:
                    instrument_bars = [
                        projected for bar in instrument_bars if (projected := aggregator.process(bar)) is not None
                    ]
                except OnlyBarAggregationError as exc:
                    raise OnlyResearchDatasetError("DATASET_DERIVED_BASE_INVALID") from exc
                if (
                    not instrument_bars
                    or instrument_bars[0].bar_start != plan.definition.time_range.start
                    or instrument_bars[-1].bar_end < plan.definition.time_range.end - timedelta(microseconds=1)
                ):
                    raise OnlyResearchDatasetError("DATASET_DERIVED_RANGE_INCOMPLETE")
            bars.extend(instrument_bars)
            provenance.append(
                OnlyResearchDatasetProvenance(
                    scope.instrument_id,
                    scope.source_id,
                    "durable-market-data",
                    "1",
                    scope.data_version,
                    None,
                    ((str(scope.start_ns), str(scope.end_ns)),),
                    ((str(scope.start_ns), str(scope.end_ns)),),
                    {
                        "bar_construction_fingerprint": construction.fingerprint,
                        "construction_recipe": construction.plan.resolved_recipe.to_dict(),
                    },
                )
            )
            revision_bindings.append(
                OnlyMarketDataRevisionBinding(
                    scope.source_id,
                    scope.instrument_id,
                    scope.data_kind,
                    revision.revision_id,
                    revision.fingerprint,
                )
            )
            construction_bindings.append(
                (scope.instrument_id, construction.fingerprint, revision.fingerprint, seal.seal_id)
            )
        canonical = only_canonical_bars(tuple(bars))
        only_validate_dataset_bars(plan.definition, canonical)
        content = only_content_fingerprint(canonical)
        construction_fingerprint = only_canonical_fingerprint(tuple(construction_bindings))
        fingerprint = only_snapshot_fingerprint(
            plan.definition,
            RESEARCH_BAR_DATASET_SCHEMA_V2,
            content,
            len(canonical),
            construction_fingerprint,
        )
        created_at = self._audit_time()
        if created_at.tzinfo is None or created_at.utcoffset() != timedelta(0):
            raise OnlyResearchDatasetError("DATASET_INPUT_INVALID: audit time must be UTC")
        snapshot = OnlyResearchDatasetSnapshot(
            plan.definition,
            RESEARCH_BAR_DATASET_SCHEMA_V2,
            content,
            len(canonical),
            fingerprint,
            (),
            tuple(provenance),
            created_at,
            construction_fingerprint,
        )
        partitions = tuple(
            tuple(bar for bar in canonical if bar.instrument_id == instrument_id)
            for instrument_id in plan.definition.instruments
        )
        committed = self._store.commit(snapshot, partitions)
        ordered_revision_bindings = tuple(
            sorted(
                revision_bindings,
                key=lambda item: (item.source_id, item.instrument_id, item.data_kind),
            )
        )
        request_fingerprint = only_canonical_fingerprint(
            {
                "definition": plan.definition,
                "scopes": tuple(scope for scope, _, _, _ in bindings),
                "constructions": tuple(item.fingerprint for _, _, item, _ in bindings),
            }
        )
        materializer_id = "onlyalpha.sealed-market-data"
        materializer_version = "1"
        materialization = OnlyDatasetMaterialization(
            only_dataset_materialization_id(
                committed.snapshot_fingerprint,
                ordered_revision_bindings,
                materializer_id,
                materializer_version,
                request_fingerprint,
            ),
            committed.snapshot_fingerprint,
            ordered_revision_bindings,
            materializer_id,
            materializer_version,
            request_fingerprint,
            created_at,
        )
        committed_materialization = self._materialization_store.commit_materialization(materialization)
        return OnlySealedMarketDataMaterializationResult(committed, committed_materialization)


__all__ = [
    "OnlySealedMarketDataDatasetMaterializer",
    "OnlySealedMarketDataMaterializationPlan",
    "OnlySealedMarketDataMaterializationResult",
]
