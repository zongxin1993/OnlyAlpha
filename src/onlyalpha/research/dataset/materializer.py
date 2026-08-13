"""Finite orchestration from historical acquisition to immutable Snapshot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import cast

from onlyalpha.cache.historical.api import OnlyHistoricalCacheProvider
from onlyalpha.cache.historical.service import OnlyHistoricalCacheService
from onlyalpha.data.historical import OnlyHistoricalDataProviderCreateRequest, OnlyHistoricalDataRequest
from onlyalpha.domain.market import OnlyBar, OnlyBarType

from .identity import only_canonical_bars, only_content_fingerprint, only_snapshot_fingerprint
from .manifest import OnlyResearchDatasetProvenance, OnlyResearchDatasetSnapshot
from .plan import OnlyResearchDatasetMaterializationPlan
from .ports import OnlyResearchDatasetSnapshotStore
from .schema import RESEARCH_BAR_DATASET_SCHEMA_V1
from .validation import OnlyResearchDatasetError, only_validate_dataset_bars


class OnlyResearchDatasetMaterializer:
    def __init__(
        self,
        cache: OnlyHistoricalCacheService,
        store: OnlyResearchDatasetSnapshotStore,
        audit_time: Callable[[], datetime],
    ) -> None:
        self._cache = cache
        self._store = store
        self._audit_time = audit_time

    def materialize(self, plan: OnlyResearchDatasetMaterializationPlan) -> OnlyResearchDatasetSnapshot:
        bars: list[OnlyBar] = []
        provenance: list[OnlyResearchDatasetProvenance] = []
        for instrument_id in plan.definition.instruments:
            instrument = plan.instruments.get(instrument_id)
            if instrument is None or instrument.trading_calendar_id is None:
                raise OnlyResearchDatasetError("DATASET_INPUT_INVALID: unresolved instrument/calendar")
            calendar = plan.calendars.get(instrument.trading_calendar_id)
            if calendar is None:
                raise OnlyResearchDatasetError("DATASET_INPUT_INVALID: unresolved calendar")
            provider = plan.provider_factory.create_historical_provider(
                OnlyHistoricalDataProviderCreateRequest(
                    plan.source_id,
                    plan.plugin_config,
                    instrument,
                    calendar,
                    plan.data_version,
                    plan.batch_size,
                    plan.config_directory,
                )
            )
            request = OnlyHistoricalDataRequest(
                instrument_id,
                OnlyBarType(instrument_id, plan.definition.bar_specification, plan.definition.aggregation_source),
                plan.definition.time_range,
                plan.definition.adjustment_type,
                plan.definition.adjustment_reference,
            )
            result = self._cache.load(request, cast(OnlyHistoricalCacheProvider, provider), plan.cache_policy)
            bars.extend(result.records)
            provenance.append(
                OnlyResearchDatasetProvenance(
                    str(instrument_id),
                    str(plan.source_id),
                    plan.plugin_id,
                    plan.plugin_version,
                    str(plan.data_version),
                    result.manifest.content_fingerprint,
                    tuple((item.start.isoformat(), item.end.isoformat()) for item in result.manifest.resolved_ranges),
                    tuple((item.start.isoformat(), item.end.isoformat()) for item in result.manifest.observed_ranges),
                    result.manifest.metadata,
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
