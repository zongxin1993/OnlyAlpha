"""Stable storage ports; infrastructure implementations live under persistence."""

from __future__ import annotations

from typing import Protocol

from .models import (
    OnlyCanonicalMarketFactRecord,
    OnlyCoverageManifest,
    OnlyIngestSegment,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataRecordBundle,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSeal,
)


class OnlyMarketFactStore(Protocol):
    def inspect_segment(self, segment: OnlyIngestSegment) -> str: ...
    def write_segment(self, segment: OnlyIngestSegment, records: tuple[OnlyMarketDataRecordBundle, ...]) -> None: ...
    def verify_segment(self, segment: OnlyIngestSegment, records: tuple[OnlyMarketDataRecordBundle, ...]) -> None: ...
    def read_revision_facts(
        self, revision: OnlyMarketDataRevision, scope: OnlyMarketDataScope
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]: ...
    def read_segment_facts(
        self, segments: tuple[OnlyIngestSegment, ...], scope: OnlyMarketDataScope
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]: ...


class OnlyMarketDataCatalog(Protocol):
    def commit_durable_segments(self, segments: tuple[OnlyIngestSegment, ...]) -> None: ...
    def commit_acquisition_intent(self, intent: OnlyMarketDataAcquisitionIntent) -> None: ...
    def commit_coverage_manifest(self, manifest: OnlyCoverageManifest) -> None: ...
    def commit_revision(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        manifest: OnlyCoverageManifest,
        revision: OnlyMarketDataRevision,
        seal: OnlyMarketDataSeal,
    ) -> None: ...
    def is_segment_committed(self, segment_id: str, content_hash: str) -> bool: ...
    def load_durable_segments(self, segment_ids: tuple[str, ...]) -> tuple[OnlyIngestSegment, ...]: ...
    def list_durable_segments(self, scope: OnlyMarketDataScope) -> tuple[OnlyIngestSegment, ...]: ...
    def load_sealed_revision(self, revision_id: str) -> tuple[OnlyMarketDataRevision, OnlyMarketDataSeal]: ...
    def latest_sealed_revision(self, scope: OnlyMarketDataScope) -> OnlyMarketDataRevision: ...


__all__ = [name for name in globals() if name.startswith("Only")]
