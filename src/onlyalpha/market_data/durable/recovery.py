"""Deterministic cross-system drain and crash recovery protocol."""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from threading import Lock
from time import perf_counter_ns

from .models import OnlyIngestSegment, OnlyMarketDataHealth, OnlyMarketDataProvenance, OnlyMarketDataScope
from .performance import only_market_data_timed
from .ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from .revision import OnlyRevisionCommitService, _OnlyVerifiedMarketDataCompletion
from .wal import OnlyMarketDataWal

_LOGGER = logging.getLogger(__name__)


class OnlyMarketDataCrashBoundary(StrEnum):
    C1_BEFORE_WAL_DURABLE = "C1"
    C2_WAL_DURABLE_BEFORE_SEAL = "C2"
    C3_SEALED_BEFORE_STORE = "C3"
    C4_RAW_BEFORE_CANONICAL = "C4"
    C5_STORE_BEFORE_VERIFY = "C5"
    C6_VERIFIED_BEFORE_CATALOG = "C6"
    C7_CATALOG_BEFORE_GC = "C7"


class OnlyInjectedMarketDataCrash(RuntimeError):
    pass


class OnlyMarketDataRecoveryCoordinator:
    def __init__(
        self,
        wal: OnlyMarketDataWal,
        fact_store: OnlyMarketFactStore,
        catalog: OnlyMarketDataCatalog,
        revision_committer: OnlyRevisionCommitService,
        *,
        barrier: Callable[[OnlyMarketDataCrashBoundary], None] | None = None,
    ) -> None:
        self._wal = wal
        self._facts = fact_store
        self._catalog = catalog
        self._committer = revision_committer
        self._barrier = barrier or (lambda _: None)
        self._state_lock = Lock()
        self._recovery_count = 0
        self._last_recovery_error: str | None = None
        self._last_verified_segment: str | None = None
        self._last_committed_segment: str | None = None
        self._completion: _OnlyVerifiedMarketDataCompletion | None = None

    def drain(self, segment_id: str, scope: OnlyMarketDataScope) -> str:
        return self.drain_revision((segment_id,), scope)

    def drain_revision(self, segment_ids: tuple[str, ...], scope: OnlyMarketDataScope) -> str:
        result = self._run_revision(segment_ids, scope, should_continue=lambda: True)
        if result is None:  # pragma: no cover - unconditional continuation
            raise RuntimeError("MARKET_DATA_RECOVERY_INTERRUPTED")
        return result

    def _run_revision(
        self,
        segment_ids: tuple[str, ...],
        scope: OnlyMarketDataScope,
        *,
        should_continue: Callable[[], bool],
    ) -> str | None:
        with self._state_lock:
            self._recovery_count += 1
        try:
            return self._drain_revision(segment_ids, scope, should_continue=should_continue)
        except Exception as exc:
            with self._state_lock:
                self._last_recovery_error = f"{type(exc).__name__}:{exc}"
            raise

    def _drain_revision(
        self,
        segment_ids: tuple[str, ...],
        scope: OnlyMarketDataScope,
        *,
        should_continue: Callable[[], bool],
    ) -> str | None:
        if not segment_ids or len(set(segment_ids)) != len(segment_ids):
            raise ValueError("MARKET_DATA_RECOVERY_SEGMENT_SET_INVALID")
        segments: list[OnlyIngestSegment] = []
        for segment_id in sorted(segment_ids):
            if not should_continue():
                return None
            segments.append(self._wal.load_segment(segment_id))
        if not should_continue():
            return None
        committed = self._catalog.segments_committed(tuple(segments))
        if any(committed) and not all(committed):
            raise RuntimeError("MARKET_DATA_RECOVERY_COMMIT_SET_CONFLICT")
        records_by_segment = {}
        for segment in segments:
            if not should_continue():
                return None
            records_by_segment[segment.segment_id] = self._wal.read_sealed(segment.segment_id)
        store_started = perf_counter_ns()
        if not all(committed):
            self._barrier(OnlyMarketDataCrashBoundary.C3_SEALED_BEFORE_STORE)
            self._facts.write_segments(tuple(segments), records_by_segment)
        batch_store_ms = (perf_counter_ns() - store_started) // 1_000_000
        self._barrier(OnlyMarketDataCrashBoundary.C5_STORE_BEFORE_VERIFY)
        verify_started = perf_counter_ns()
        verified = self._facts.verify_segments(tuple(segments), records_by_segment, scope)
        batch_verify_ms = (perf_counter_ns() - verify_started) // 1_000_000
        with self._state_lock:
            self._last_verified_segment = segments[-1].segment_id
        if not should_continue():
            return None
        self._barrier(OnlyMarketDataCrashBoundary.C6_VERIFIED_BEFORE_CATALOG)
        catalog_started = perf_counter_ns()
        reason = {
            OnlyMarketDataProvenance.REST_BACKFILL: "BACKFILL",
            OnlyMarketDataProvenance.REPAIR: "CORRECTION",
            OnlyMarketDataProvenance.REPLAY: "REPLAY",
        }.get(segments[0].capture_mode, "INGEST")
        manifest, revision, _ = self._committer.commit_if_complete(
            tuple(segments), scope, records_by_segment, verified_batch=verified, reason=reason
        )
        catalog_commit_ms = (perf_counter_ns() - catalog_started) // 1_000_000
        _LOGGER.info(
            "market_data_recovery_batch wal_segment_count=%d canonical_fact_count=%d "
            "batch_store_ms=%d batch_verify_ms=%d catalog_commit_ms=%d",
            len(segments),
            sum(item.canonical_count for item in segments),
            batch_store_ms,
            batch_verify_ms,
            catalog_commit_ms,
        )
        with self._state_lock:
            self._last_committed_segment = segments[-1].segment_id
            self._last_recovery_error = None
        self._barrier(OnlyMarketDataCrashBoundary.C7_CATALOG_BEFORE_GC)
        for segment in segments:
            if not should_continue():
                return None
            self._wal.mark_gc_eligible(segment.segment_id)
            self._wal.collect_garbage(segment.segment_id)
        if revision is None:
            return f"DURABLE_ONLY:{manifest.coverage_status.value}"
        self._completion = self._committer._completion
        return "ALREADY_COMMITTED" if all(committed) else "COMMITTED"

    @only_market_data_timed("recovery_total")
    def recover_all(self, *, should_continue: Callable[[], bool] | None = None) -> tuple[str, ...]:
        self._completion = None
        continue_recovery = should_continue or (lambda: True)
        if not continue_recovery():
            return ()
        self._wal.resolve_creation_orphans()
        for segment_id in self._wal.scan_gc_eligible():
            if not continue_recovery():
                return ()
            if segment_id in self._wal.scan_uncommitted():
                self._wal.mark_gc_eligible(segment_id)
            self._wal.collect_garbage(segment_id)
        self._wal.assert_no_metadata_orphans()
        for segment_id in self._wal.scan_open():
            if not continue_recovery():
                return ()
            recovered = self._wal.recover_open(segment_id)
            if recovered.valid_records == 0 and recovered.quarantined_tail is None:
                self._wal.abandon_empty_open(segment_id)
            else:
                self._wal.seal_recovered_open(segment_id)
        self._wal.resolve_sealed_metadata_orphans()
        return self.recover_sealed(should_continue=continue_recovery)

    def recover_sealed(self, *, should_continue: Callable[[], bool] | None = None) -> tuple[str, ...]:
        """Drain sealed WAL while a live writer may own an open segment."""
        continue_recovery = should_continue or (lambda: True)
        results: list[str] = []
        self._completion = None
        groups: dict[tuple[object, ...], tuple[list[str], list[OnlyMarketDataScope]]] = {}
        for segment_id in self._wal.scan_published_uncommitted():
            if not continue_recovery():
                return tuple(results)
            segment = self._wal.load_segment(segment_id)
            if segment.canonical_count == 0:
                if not self._ensure_exact(segment, should_continue=continue_recovery):
                    return tuple(results)
                results.append("DURABLE_ONLY:RAW_ONLY")
                continue
            scope = segment.recovery_scope()
            key = (
                segment.capture_session_id,
                segment.source_id,
                segment.market,
                segment.stream,
                segment.provider,
                segment.venue,
                segment.capture_mode,
                scope.instrument_id,
                scope.data_kind,
                scope.data_version,
                scope.bar_type,
                None if scope.bar_construction is None else scope.bar_construction.fingerprint,
            )
            entry = groups.setdefault(key, ([], []))
            entry[0].append(segment_id)
            entry[1].append(scope)
        for _, value in sorted(groups.items(), key=lambda item: repr(item[0])):
            if not continue_recovery():
                break
            segment_ids = tuple(value[0])
            scopes = tuple(value[1])
            scope = _merge_recovery_scopes(scopes)
            result = self._run_revision(segment_ids, scope, should_continue=continue_recovery)
            if result is None:
                break
            results.append(result)
        return tuple(results)

    def _ensure_exact(self, segment: OnlyIngestSegment, *, should_continue: Callable[[], bool]) -> bool:
        if not should_continue():
            return False
        records = self._wal.read_sealed(segment.segment_id)
        if not should_continue():
            return False
        committed = self._catalog.segments_committed((segment,))[0]
        if not committed:
            self._barrier(OnlyMarketDataCrashBoundary.C3_SEALED_BEFORE_STORE)
            self._facts.write_segments((segment,), {segment.segment_id: records})
        self._barrier(OnlyMarketDataCrashBoundary.C5_STORE_BEFORE_VERIFY)
        verified = self._facts.verify_segments((segment,), {segment.segment_id: records})
        with self._state_lock:
            self._last_verified_segment = segment.segment_id
        if not should_continue():
            return False
        self._barrier(OnlyMarketDataCrashBoundary.C6_VERIFIED_BEFORE_CATALOG)
        self._catalog.commit_durable_segments((segment,), verified.physical_proofs)
        with self._state_lock:
            self._last_committed_segment = segment.segment_id
            self._last_recovery_error = None
        self._barrier(OnlyMarketDataCrashBoundary.C7_CATALOG_BEFORE_GC)
        self._wal.mark_gc_eligible(segment.segment_id)
        self._wal.collect_garbage(segment.segment_id)
        return True

    def health(self) -> OnlyMarketDataHealth:
        with self._state_lock:
            last_verified_segment = self._last_verified_segment
            last_committed_segment = self._last_committed_segment
            recovery_count = self._recovery_count
            last_recovery_error = self._last_recovery_error
        return self._wal.health(
            last_verified_segment=last_verified_segment,
            last_committed_segment=last_committed_segment,
            recovery_count=recovery_count,
            last_recovery_error=last_recovery_error,
        )


def _merge_recovery_scopes(scopes: tuple[OnlyMarketDataScope, ...]) -> OnlyMarketDataScope:
    if not scopes:
        raise ValueError("MARKET_DATA_RECOVERY_SCOPE_EMPTY")
    first = scopes[0]
    identity = (
        first.source_id,
        first.market,
        first.instrument_id,
        first.data_kind,
        first.data_version,
        first.bar_type,
        first.bar_construction,
    )
    if any(
        (
            item.source_id,
            item.market,
            item.instrument_id,
            item.data_kind,
            item.data_version,
            item.bar_type,
            item.bar_construction,
        )
        != identity
        for item in scopes
    ):
        raise RuntimeError("MARKET_DATA_RECOVERY_SCOPE_CONFLICT")
    sequences = tuple(
        (item.first_sequence, item.last_sequence)
        for item in scopes
        if item.first_sequence is not None and item.last_sequence is not None
    )
    return OnlyMarketDataScope(
        first.source_id,
        first.market,
        first.instrument_id,
        first.data_kind,
        min(item.start_ns for item in scopes),
        max(item.end_ns for item in scopes),
        first.data_version,
        first.bar_type,
        min(item[0] for item in sequences) if len(sequences) == len(scopes) else None,
        max(item[1] for item in sequences) if len(sequences) == len(scopes) else None,
        first.bar_construction,
    )


__all__ = [name for name in globals() if name.startswith("Only")]
