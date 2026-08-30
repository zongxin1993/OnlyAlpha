"""Deterministic cross-system drain and crash recovery protocol."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from .models import OnlyMarketDataHealth, OnlyMarketDataScope
from .ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from .revision import OnlyRevisionCommitService
from .wal import OnlyMarketDataWal


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
        self._recovery_count = 0
        self._last_recovery_error: str | None = None
        self._last_verified_segment: str | None = None
        self._last_committed_segment: str | None = None

    def drain(self, segment_id: str, scope: OnlyMarketDataScope) -> str:
        return self.drain_revision((segment_id,), scope)

    def drain_revision(self, segment_ids: tuple[str, ...], scope: OnlyMarketDataScope) -> str:
        self._recovery_count += 1
        try:
            return self._drain_revision(segment_ids, scope)
        except Exception as exc:
            self._last_recovery_error = f"{type(exc).__name__}:{exc}"
            raise

    def _drain_revision(self, segment_ids: tuple[str, ...], scope: OnlyMarketDataScope) -> str:
        if not segment_ids or len(set(segment_ids)) != len(segment_ids):
            raise ValueError("MARKET_DATA_RECOVERY_SEGMENT_SET_INVALID")
        segments = tuple(self._wal.load_segment(segment_id) for segment_id in sorted(segment_ids))
        committed = tuple(
            self._catalog.is_segment_committed(segment.segment_id, segment.content_hash) for segment in segments
        )
        if any(committed) and not all(committed):
            raise RuntimeError("MARKET_DATA_RECOVERY_COMMIT_SET_CONFLICT")
        if all(committed):
            self._barrier(OnlyMarketDataCrashBoundary.C7_CATALOG_BEFORE_GC)
            for segment in segments:
                self._wal.mark_gc_eligible(segment.segment_id)
            return "ALREADY_COMMITTED"
        records_by_segment = {segment.segment_id: self._wal.read_sealed(segment.segment_id) for segment in segments}
        for segment in segments:
            state = self._facts.inspect_segment(segment)
            if state == "CONFLICT":
                raise RuntimeError("MARKET_DATA_STORE_CONFLICT")
            if state != "EXACT":
                self._barrier(OnlyMarketDataCrashBoundary.C3_SEALED_BEFORE_STORE)
                self._facts.write_segment(segment, records_by_segment[segment.segment_id])
            self._barrier(OnlyMarketDataCrashBoundary.C5_STORE_BEFORE_VERIFY)
            self._facts.verify_segment(segment, records_by_segment[segment.segment_id])
            self._last_verified_segment = segment.segment_id
        self._barrier(OnlyMarketDataCrashBoundary.C6_VERIFIED_BEFORE_CATALOG)
        self._committer.commit(segments, scope, records_by_segment)
        self._last_committed_segment = segments[-1].segment_id
        self._last_recovery_error = None
        self._barrier(OnlyMarketDataCrashBoundary.C7_CATALOG_BEFORE_GC)
        for segment in segments:
            self._wal.mark_gc_eligible(segment.segment_id)
        return "COMMITTED"

    def recover_all(self, scopes: dict[str, OnlyMarketDataScope]) -> tuple[str, ...]:
        results: list[str] = []
        for segment_id in self._wal.scan_open():
            recovered = self._wal.recover_open(segment_id)
            if recovered.valid_records == 0 and recovered.quarantined_tail is None:
                self._wal.abandon_empty_open(segment_id)
            else:
                self._wal.seal_recovered_open(segment_id)
        groups: dict[OnlyMarketDataScope, list[str]] = {}
        for segment_id in self._wal.scan_uncommitted():
            scope = scopes.get(segment_id)
            if scope is None:
                raise RuntimeError(f"MARKET_DATA_RECOVERY_SCOPE_MISSING:{segment_id}")
            groups.setdefault(scope, []).append(segment_id)
        for scope, segment_ids in sorted(groups.items(), key=lambda item: repr(item[0])):
            results.append(self.drain_revision(tuple(segment_ids), scope))
        return tuple(results)

    def health(self) -> OnlyMarketDataHealth:
        return self._wal.health(
            last_verified_segment=self._last_verified_segment,
            last_committed_segment=self._last_committed_segment,
            recovery_count=self._recovery_count,
            last_recovery_error=self._last_recovery_error,
        )


__all__ = [name for name in globals() if name.startswith("Only")]
