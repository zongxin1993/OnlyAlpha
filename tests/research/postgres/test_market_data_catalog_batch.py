from __future__ import annotations

from dataclasses import replace

import psycopg
import pytest

from onlyalpha.market_data.durable import (
    OnlyBarCoverageGap,
    OnlyCoverageStatus,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataConflictError,
    OnlyMarketDataRangeFamily,
    OnlyMarketDataRevision,
    OnlyMarketDataSealError,
    OnlyRevisionCommitService,
    OnlyVerifiedMarketDataRangeQuery,
    only_build_coverage,
    only_build_seal,
)
from onlyalpha.persistence.postgres import OnlyPostgresMarketDataCatalog
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from tests.market_data_durable.conftest import BASE
from tests.market_data_durable.test_recovery_revision_dataset import _scope, _sealed

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def _history(dsn, root, count):
    OnlyPostgresMigrationAuthority(dsn).migrate()
    catalog = OnlyPostgresMarketDataCatalog(dsn)
    store = OnlyInMemoryMarketFactStore()
    entries = []
    for index in range(count):
        wal, segment, _ = _sealed(
            root / str(index), lambda: BASE.replace(hour=1), kind="BAR", close=f"100.{index:08d}", bar_index=index
        )
        records = wal.read_sealed(segment.segment_id)
        store.write_segment(segment, records)
        scope = replace(
            _scope("BAR"),
            start_ns=_scope("BAR").start_ns + index * 60_000_000_000,
            end_ns=_scope("BAR").end_ns + index * 60_000_000_000,
        )
        entries.append(
            OnlyRevisionCommitService(store, catalog, now=lambda: BASE.replace(hour=1)).commit(
                segment, scope, {segment.segment_id: records}
            )
        )
    return catalog, store, tuple(entries)


def _count_reads(monkeypatch):
    counts = {"connections": 0, "selects": 0}
    connect = psycopg.connect

    class CountedConnection:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, query, parameters=None):
            assert query.lstrip().startswith("SELECT"), "counted window path must remain read-only"
            counts["selects"] += 1
            return self.connection.execute(query, parameters)

    def counted(*args, **kwargs):
        counts["connections"] += 1
        return CountedConnection(connect(*args, **kwargs))

    monkeypatch.setattr(psycopg, "connect", counted)
    return counts


@pytest.mark.parametrize("count", [1, 12])
def test_exact_range_metadata_batch_count_does_not_grow_per_revision(postgres_dsn, tmp_path, monkeypatch, count):
    catalog, store, entries = _history(postgres_dsn, tmp_path, count)
    revisions = tuple(row[1] for row in entries)
    family = OnlyMarketDataRangeFamily.from_scope(revisions[0].scope)
    counts = _count_reads(monkeypatch)
    result = OnlyVerifiedMarketDataRangeQuery(catalog, store).read(
        family, tuple(OnlyBarCoverageGap(row.scope.start_ns, row.scope.end_ns) for row in revisions)
    )
    assert result.coverage_status is OnlyCoverageStatus.COMPLETE
    assert len(result.facts) == count
    assert tuple(item.revision_id for item in result.evidence) == tuple(row.revision_id for row in revisions)
    assert counts == {"connections": 6, "selects": 9}


def test_metadata_batch_order_empty_duplicates_and_missing_are_exact(postgres_dsn, tmp_path, monkeypatch):
    catalog, store, entries = _history(postgres_dsn, tmp_path, 3)
    ids = tuple(ref[0] for _, revision, _ in entries for ref in revision.segment_refs)
    segments = catalog.load_durable_segments(ids)
    scope = replace(entries[0][1].scope, end_ns=entries[-1][1].scope.end_ns)
    facts = store.read_segment_facts(segments, scope, catalog.load_physical_proofs(ids))
    manifest = only_build_coverage(scope, segments, facts)
    revision = OnlyMarketDataRevision.build(manifest, normalizers=entries[0][1].normalizers, creation_reason="COMPOSE")
    seal = only_build_seal(revision, manifest, sealed_at=BASE.replace(hour=1))
    catalog.commit_revision(segments, manifest, revision, seal)
    entries += ((manifest, revision, seal),)
    counts = _count_reads(monkeypatch)
    revisions = tuple(row[1].revision_id for row in reversed(entries))
    manifests = tuple(row[0].manifest_id for row in reversed(entries))
    assert catalog.load_sealed_revisions(revisions) == tuple((row[1], row[2]) for row in reversed(entries))
    assert catalog.load_coverage_manifests(manifests) == tuple(row[0] for row in reversed(entries))
    assert counts == {"connections": 2, "selects": 4}
    assert catalog.load_sealed_revisions(()) == catalog.load_coverage_manifests(()) == ()
    for method, ids in [(catalog.load_sealed_revisions, revisions), (catalog.load_coverage_manifests, manifests)]:
        with pytest.raises(ValueError, match="MARKET_DATA_METADATA_READ_SET_INVALID"):
            method((ids[0], ids[0]))
        with pytest.raises(KeyError):
            method((ids[0], "missing-metadata"))
    assert counts == {"connections": 4, "selects": 8}


@pytest.mark.parametrize(
    "fault",
    [
        "missing-revision",
        "reordered-revisions",
        "extra-revision",
        "missing-manifest",
        "reordered-manifests",
        "changed-listed",
        "cross-seal",
        "cross-manifest",
        "missing-segment",
        "reordered-segments",
        "segment-hash",
        "missing-proof",
        "wrong-proof",
    ],
)
def test_range_batch_keeps_every_exact_authority_binding(postgres_dsn, tmp_path, monkeypatch, fault):
    catalog, store, entries = _history(postgres_dsn, tmp_path, 2)
    revisions = tuple(row[1] for row in entries)
    family = OnlyMarketDataRangeFamily.from_scope(revisions[0].scope)
    if fault in {"missing-revision", "reordered-revisions", "extra-revision", "changed-listed", "cross-seal"}:
        original = catalog.load_sealed_revisions
        calls = 0

        def sealed(ids):
            nonlocal calls
            rows = original(ids)
            calls += 1
            if calls == 1:  # the selector's observation remains exact
                return rows
            if fault == "missing-revision":
                return rows[:-1]
            if fault == "reordered-revisions":
                return tuple(reversed(rows))
            if fault == "extra-revision":
                return rows + rows[:1]
            if fault == "changed-listed":
                return ((replace(rows[0][0], creation_reason="changed"), rows[0][1]),) + rows[1:]
            return ((rows[0][0], rows[1][1]),) + rows[1:]

        monkeypatch.setattr(catalog, "load_sealed_revisions", sealed)
    elif fault in {"missing-manifest", "reordered-manifests", "cross-manifest"}:
        original = catalog.load_coverage_manifests

        def manifests(ids):
            rows = original(ids)
            if fault == "missing-manifest":
                return rows[:-1]
            if fault == "reordered-manifests":
                return tuple(reversed(rows))
            return (replace(rows[0], segment_refs=rows[1].segment_refs),) + rows[1:]

        monkeypatch.setattr(catalog, "load_coverage_manifests", manifests)
    elif fault in {"missing-segment", "reordered-segments", "segment-hash"}:
        original = catalog.load_durable_segments

        def segments(ids):
            rows = original(ids)
            if fault == "missing-segment":
                return rows[:-1]
            if fault == "reordered-segments":
                return tuple(reversed(rows))
            return (replace(rows[0], content_hash="0" * 64),) + rows[1:]

        monkeypatch.setattr(catalog, "load_durable_segments", segments)
    else:
        original = catalog.load_physical_proofs

        def proofs(ids):
            rows = original(ids)
            if fault == "missing-proof":
                return rows[:-1]
            return (replace(rows[0], segment_content_hash="0" * 64),) + rows[1:]

        monkeypatch.setattr(catalog, "load_physical_proofs", proofs)
    with pytest.raises(
        (OnlyMarketDataSealError, OnlyMarketDataConflictError, ValueError), match="MARKET_DATA_|REVISION_"
    ):
        OnlyVerifiedMarketDataRangeQuery(catalog, store).read(
            family, tuple(OnlyBarCoverageGap(row.scope.start_ns, row.scope.end_ns) for row in revisions)
        )
