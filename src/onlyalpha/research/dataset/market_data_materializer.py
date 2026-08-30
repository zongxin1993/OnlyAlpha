"""Immutable Dataset materialization from one exact sealed Market Data Revision."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.market_data.durable.models import OnlyMarketDataScope
from onlyalpha.market_data.durable.revision import OnlyHistoricalMarketDataQueryService

from .definition import OnlyResearchDatasetDefinition
from .identity import only_canonical_bars, only_content_fingerprint, only_snapshot_fingerprint
from .manifest import OnlyResearchDatasetProvenance, OnlyResearchDatasetSnapshot
from .ports import OnlyResearchDatasetSnapshotStore
from .schema import RESEARCH_BAR_DATASET_SCHEMA_V1
from .validation import OnlyResearchDatasetError, only_validate_dataset_bars


@dataclass(frozen=True, slots=True)
class OnlySealedMarketDataMaterializationPlan:
    revision_ids: tuple[str, ...]
    definition: OnlyResearchDatasetDefinition
    scopes: tuple[OnlyMarketDataScope, ...]

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


class OnlySealedMarketDataDatasetMaterializer:
    def __init__(
        self,
        query: OnlyHistoricalMarketDataQueryService,
        store: OnlyResearchDatasetSnapshotStore,
        audit_time: Callable[[], datetime],
    ) -> None:
        self._query = query
        self._store = store
        self._audit_time = audit_time

    def materialize(self, plan: OnlySealedMarketDataMaterializationPlan) -> OnlyResearchDatasetSnapshot:
        bars = []
        provenance = []
        bindings = tuple(
            sorted(zip(plan.scopes, plan.revision_ids, strict=True), key=lambda item: item[0].instrument_id)
        )
        for scope, revision_id in bindings:
            facts = self._query.read_exact(revision_id, scope)
            instrument_bars = []
            for fact in facts:
                update = OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload)
                if not isinstance(update.payload, OnlyBarUpdate):
                    raise OnlyResearchDatasetError("DATASET_MARKET_DATA_FACT_KIND_INVALID")
                instrument_bars.append(update.payload.bar)
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
                    {"market_data_revision_id": revision_id},
                )
            )
        canonical = only_canonical_bars(tuple(bars))
        only_validate_dataset_bars(plan.definition, canonical)
        content = only_content_fingerprint(canonical)
        fingerprint = only_snapshot_fingerprint(
            plan.definition, RESEARCH_BAR_DATASET_SCHEMA_V1, content, len(canonical)
        )
        created_at = self._audit_time()
        if created_at.tzinfo is None or created_at.utcoffset() != timedelta(0):
            raise OnlyResearchDatasetError("DATASET_INPUT_INVALID: audit time must be UTC")
        snapshot = OnlyResearchDatasetSnapshot(
            plan.definition,
            RESEARCH_BAR_DATASET_SCHEMA_V1,
            content,
            len(canonical),
            fingerprint,
            (),
            tuple(provenance),
            created_at,
        )
        partitions = tuple(
            tuple(bar for bar in canonical if bar.instrument_id == instrument_id)
            for instrument_id in plan.definition.instruments
        )
        return self._store.commit(snapshot, partitions)


__all__ = ["OnlySealedMarketDataDatasetMaterializer", "OnlySealedMarketDataMaterializationPlan"]
