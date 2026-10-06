from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.market_data.durable import (
    OnlyAcquisitionOutcome,
    OnlyCoverageManifest,
    OnlyCoverageStatus,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataProvenance,
    OnlyMarketDataRangeFamily,
    OnlyMarketDataRevision,
    OnlyRevisionCommitService,
    only_build_coverage,
    only_build_seal,
)
from onlyalpha.market_data.durable.models import (
    OnlyIngestSegment,
    OnlyMarketDataPhysicalPartitionProof,
    OnlyMarketDataPhysicalSegmentProof,
)
from onlyalpha.market_data.resolution import (
    OnlyBarCapability,
    OnlyBarConstructionIdentity,
    only_plan_bar_resolution,
)
from onlyalpha.persistence.postgres import OnlyPostgresMarketDataCatalog
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from scripts.database import _backup, _restore_test
from tests.market_data_durable.conftest import BASE
from tests.market_data_durable.test_recovery_revision_dataset import _scope, _sealed
from tests.research.postgres.migration_support import copy_migrations_through

pytestmark = [
    pytest.mark.integration,
    pytest.mark.external,
    pytest.mark.requires_network,
    pytest.mark.postgres,
]


def _proof(segment: OnlyIngestSegment) -> OnlyMarketDataPhysicalSegmentProof:
    counts = {
        "market_raw_event": segment.raw_count,
        "market_trade": segment.canonical_count if segment.data_kind == "TRADE" else 0,
        "market_bar": segment.canonical_count if segment.data_kind == "BAR" else 0,
        "market_reference_price": segment.canonical_count if segment.data_kind == "MARKET_REFERENCE" else 0,
    }
    return OnlyMarketDataPhysicalSegmentProof.build(
        segment,
        tuple(OnlyMarketDataPhysicalPartitionProof(table, count, "0" * 64) for table, count in counts.items()),
    )


def test_native_construction_scope_survives_catalog_reload(postgres_dsn: str, tmp_path: Path) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    wal, legacy_segment, _ = _sealed(tmp_path / "native", lambda: BASE.replace(hour=1), kind="BAR")
    del wal
    specification = OnlyBarSemantic.fixed_duration(1)
    scope = _scope("BAR")
    plan = only_plan_bar_resolution(
        specification,
        (OnlyBarCapability(specification, True, True, "UTC", grid_origin_ns=0),),
        calendar_fingerprint="UTC",
        source_id=scope.source_id,
        instrument_id=scope.instrument_id,
        integration_revision_fingerprint="a" * 64,
    )
    construction = OnlyBarConstructionIdentity.build(plan, data_version=scope.data_version)
    segment = replace(legacy_segment, segment_id="native-construction-1", bar_construction=construction)
    constructed_scope = replace(scope, bar_construction=construction)
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    catalog.commit_durable_segments((segment,), (_proof(segment),))
    assert catalog.load_durable_segments((segment.segment_id,)) == (segment,)
    assert catalog.list_durable_segments(constructed_scope) == (segment,)
    assert catalog.list_durable_segments(replace(scope, bar_construction=None)) == ()
    acquisition = OnlyMarketDataAcquisitionIntent.build(
        constructed_scope.source_id,
        constructed_scope,
        provenance=OnlyMarketDataProvenance.REST_BACKFILL,
        admitted_at=BASE,
        integration_binding_fingerprint="5" * 64,
    )
    assert catalog.admit_acquisition_intent(acquisition) == acquisition
    assert catalog.load_acquisition_intent(acquisition.acquisition_id) == acquisition


def test_market_data_catalog_concurrent_commit_is_immutable_and_survives_restore(
    postgres_dsn: str, tmp_path: Path
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()

    def fixed_now():  # type: ignore[no-untyped-def]
        return BASE.replace(hour=1)

    wal, segment, _ = _sealed(tmp_path / "wal", fixed_now)
    records = wal.read_sealed(segment.segment_id)
    fact_store = OnlyInMemoryMarketFactStore()
    fact_store.write_segment(segment, records)
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    manifest, revision, seal = OnlyRevisionCommitService(fact_store, catalog, now=fixed_now).commit(
        segment, _scope("TRADE"), {segment.segment_id: records}
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda _: catalog.commit_revision((segment,), manifest, revision, seal),
                range(2),
            )
        )
    assert results == (None, None)
    assert catalog.load_sealed_revision(revision.revision_id) == (revision, seal)
    assert catalog.load_durable_segments((segment.segment_id,)) == (segment,)
    expected_proofs = fact_store.verify_segments((segment,), {segment.segment_id: records}).physical_proofs
    assert catalog.load_physical_proofs((segment.segment_id,)) == expected_proofs
    changed_parts = tuple(
        replace(item, row_set_digest="1" * 64) if item.table == "market_raw_event" else item
        for item in expected_proofs[0].partitions
    )
    conflicting_proof = OnlyMarketDataPhysicalSegmentProof.build(segment, changed_parts)
    with pytest.raises(RuntimeError, match="MARKET_DATA_PHYSICAL_PROOF_CONFLICT"):
        catalog.commit_durable_segments((segment,), (conflicting_proof,))
    assert catalog.list_durable_segments(_scope("TRADE")) == (segment,)
    acquisition = OnlyMarketDataAcquisitionIntent.build(
        "BINANCE_SPOT",
        _scope("TRADE"),
        provenance=OnlyMarketDataProvenance.REST_BACKFILL,
        admitted_at=fixed_now(),
        integration_binding_fingerprint="5" * 64,
    )
    assert catalog.admit_acquisition_intent(acquisition).admitted_at == fixed_now()
    incomplete_scope = replace(_scope("TRADE"), first_sequence=10, last_sequence=11)
    incomplete = only_build_coverage(
        incomplete_scope,
        (segment,),
        tuple(fact for bundle in records for fact in bundle.canonical_facts),
    )
    catalog.commit_coverage_manifest(incomplete)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT state FROM market_segment_state_event WHERE segment_id=%s ORDER BY state",
            (segment.segment_id,),
        ).fetchall() == [("DURABLE_SEGMENT_COMMITTED",)]
        assert connection.execute(
            "SELECT provenance FROM market_acquisition_intent WHERE acquisition_id=%s",
            (acquisition.acquisition_id,),
        ).fetchone() == ("REST_BACKFILL",)
        assert connection.execute(
            "SELECT coverage_status,gaps FROM market_coverage_manifest WHERE manifest_id=%s",
            (incomplete.manifest_id,),
        ).fetchone() == ("INCOMPLETE", [{"first_sequence": 11, "last_sequence": 11}])

    conflicting_seal = replace(
        seal,
        seal_id=f"{seal.seal_id}:conflict",
        checks=seal.checks + ("UNDECLARED_CHECK",),
        sealed_at=seal.sealed_at + timedelta(microseconds=1),
    )
    with pytest.raises(RuntimeError, match="POSTGRES_MARKET_DATA_COMMIT_CONFLICT"):
        catalog.commit_revision((segment,), manifest, revision, conflicting_seal)
    assert catalog.load_sealed_revision(revision.revision_id) == (revision, seal)

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute(
            "UPDATE market_data_revision SET creation_reason='MUTATED' WHERE revision_id=%s",
            (revision.revision_id,),
        )

    backup = tmp_path / "market-data.dump"
    target_dsn = postgres_dsn.rsplit("/", 1)[0] + "/onlyalpha_restore_test"
    admin_dsn = postgres_dsn.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
        connection.execute("CREATE DATABASE onlyalpha_restore_test")
    try:
        _backup(postgres_dsn, backup)
        _restore_test(postgres_dsn, target_dsn, backup, None)
        restored = OnlyPostgresMarketDataCatalog(target_dsn)
        assert restored.load_sealed_revision(revision.revision_id) == (revision, seal)
        assert restored.load_durable_segments((segment.segment_id,)) == (segment,)
        assert restored.load_physical_proofs((segment.segment_id,)) == expected_proofs
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='onlyalpha_restore_test'"
            )
            connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")


def test_competing_revision_reasons_reject_losing_context(postgres_dsn: str, tmp_path: Path) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    wal, segment, _ = _sealed(tmp_path / "race", lambda: BASE, close="171.00000000")
    records = wal.read_sealed(segment.segment_id)
    facts = tuple(fact for bundle in records for fact in bundle.canonical_facts)
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    catalog.commit_durable_segments((segment,), (_proof(segment),))
    store = OnlyInMemoryMarketFactStore()
    store.write_segment(segment, records)
    barrier = Barrier(2)

    def commit(reason: str):  # type: ignore[no-untyped-def]
        barrier.wait()
        return OnlyRevisionCommitService(store, catalog, now=lambda: BASE).commit_durable_facts(
            (segment,), _scope("TRADE"), facts, reason=reason
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(commit, reason) for reason in ("INGEST", "BACKFILL"))
        outcomes = tuple(future.exception() or future.result() for future in futures)
    assert sum(isinstance(item, tuple) for item in outcomes) == 1
    assert (
        sum(isinstance(item, RuntimeError) and str(item) == "REVISION_MANIFEST_CONTEXT_MISMATCH" for item in outcomes)
        == 1
    )
    manifest, revision, seal = next(item for item in outcomes if isinstance(item, tuple))
    assert revision is not None and seal is not None
    assert catalog.sealed_revision_for_manifest(manifest.manifest_id) == (revision, seal)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM market_data_revision WHERE manifest_id=%s", (manifest.manifest_id,)
        ).fetchone() == (1,)


def test_capture_session_accepts_multiple_segments_created_at_different_times(
    postgres_dsn: str, tmp_path: Path
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _, first, _ = _sealed(tmp_path / "wal", lambda: BASE)
    second = replace(
        first,
        segment_id="segment-second",
        content_hash="a" * 64,
        created_at=BASE + timedelta(seconds=1),
        sealed_at=BASE + timedelta(seconds=2),
    )
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)

    catalog.commit_durable_segments((first, second), (_proof(first), _proof(second)))

    assert catalog.load_durable_segments((first.segment_id, second.segment_id)) == (first, second)
    conflicting = replace(second, segment_id="segment-conflicting", content_hash="b" * 64, provider_schema="v2")
    with pytest.raises(RuntimeError, match="POSTGRES_CAPTURE_SESSION_CONFLICT"):
        catalog.commit_durable_segments((conflicting,), (_proof(conflicting),))


def _acquisition(source_id: str, binding: str) -> OnlyMarketDataAcquisitionIntent:
    return OnlyMarketDataAcquisitionIntent.build(
        source_id,
        _scope("TRADE"),
        provenance=OnlyMarketDataProvenance.REST_BACKFILL,
        admitted_at=BASE,
        integration_binding_fingerprint=binding,
    )


def test_pre_0038_acquisition_identity_remains_exactly_readable(postgres_dsn: str, tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy-migrations"
    legacy_root.mkdir()
    copy_migrations_through(legacy_root, "0037_market_data_acquisition_attempt")
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=legacy_root).migrate()
    scope = _scope("TRADE")
    fingerprint = only_canonical_fingerprint(
        {
            "source_id": "BINANCE_SPOT_LEGACY",
            "requested_scope": scope,
            "provenance": OnlyMarketDataProvenance.REST_BACKFILL.value,
        }
    )
    acquisition_id = f"acquisition:{fingerprint}"
    attempt_detail = "LEGACY_PROVIDER_FAILURE"
    attempt_fingerprint = only_canonical_fingerprint(
        {
            "acquisition_id": acquisition_id,
            "outcome": OnlyAcquisitionOutcome.FAILED.value,
            "revision_id": None,
            "detail": attempt_detail,
        }
    )
    attempt_id = f"acquisition-attempt:{attempt_fingerprint}"
    admitted_at = BASE.replace(hour=2)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO market_acquisition_intent "
            "(acquisition_id,request_fingerprint,source_id,requested_scope,provenance,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                acquisition_id,
                fingerprint,
                "BINANCE_SPOT_LEGACY",
                psycopg.types.json.Jsonb(only_canonical_payload(scope)),
                OnlyMarketDataProvenance.REST_BACKFILL.value,
                admitted_at,
            ),
        )
        connection.execute(
            "INSERT INTO market_data_acquisition_attempt "
            "(attempt_id,acquisition_id,outcome,revision_id,detail,recorded_at) "
            "VALUES (%s,%s,'FAILED',NULL,%s,%s)",
            (attempt_id, acquisition_id, attempt_detail, admitted_at),
        )

    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == (
        "0038_market_data_acquisition_identity",
        "0039_market_data_acquisition_versioned_attempt_outcome",
        "0040_market_bar_construction_identity",
        "0041_market_data_range_lookup",
        "0042_market_segment_physical_proof",
        "0043_chart_calculation_admission",
        "0044_research_run_id_reservation",
    )
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    loaded = catalog.load_acquisition_intent(acquisition_id)
    attempt = catalog.latest_acquisition_attempt(acquisition_id)

    assert loaded is not None
    assert loaded.acquisition_id == acquisition_id
    assert loaded.request_fingerprint == fingerprint
    assert loaded.admitted_at == admitted_at
    assert loaded.identity_version == 1
    assert loaded.integration_binding_fingerprint is None
    assert attempt is not None
    assert attempt.attempt_id == attempt_id
    assert attempt.attempt_number == 1
    assert attempt.identity_version == 1
    assert attempt.outcome is OnlyAcquisitionOutcome.FAILED
    assert attempt.started_at == admitted_at
    assert attempt.completed_at == admitted_at
    assert attempt.detail == attempt_detail


def test_attempt_start_is_atomic_per_intent_and_keeps_interrupted_occurrences(
    postgres_dsn: str,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    first = catalog.admit_acquisition_intent(_acquisition("BINANCE_SPOT", "1" * 64))
    second = catalog.admit_acquisition_intent(_acquisition("BINANCE_SPOT_TESTNET", "2" * 64))
    barrier = Barrier(10)

    def start_same(_: int) -> int:
        barrier.wait()
        return catalog.start_acquisition_attempt(first.acquisition_id, started_at=BASE).attempt_number

    with ThreadPoolExecutor(max_workers=10) as executor:
        numbers = tuple(executor.map(start_same, range(10)))

    assert set(numbers) == set(range(1, 11))
    latest = catalog.latest_acquisition_attempt(first.acquisition_id)
    assert latest is not None
    assert latest.attempt_number == 10
    assert latest.outcome is None and latest.completed_at is None

    distinct_barrier = Barrier(2)

    def start_distinct(acquisition_id: str) -> int:
        distinct_barrier.wait()
        return catalog.start_acquisition_attempt(acquisition_id, started_at=BASE).attempt_number

    with ThreadPoolExecutor(max_workers=2) as executor:
        distinct = tuple(executor.map(start_distinct, (first.acquisition_id, second.acquisition_id)))
    assert distinct == (11, 1)


def test_acquisition_execution_lease_is_cross_catalog_and_released(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    first_catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    second_catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    first = first_catalog.admit_acquisition_intent(_acquisition("BINANCE_SPOT", "1" * 64))
    second = first_catalog.admit_acquisition_intent(_acquisition("BINANCE_SPOT_TESTNET", "2" * 64))

    with psycopg.connect(postgres_dsn) as connection:
        before = connection.execute("SELECT count(*) FROM market_acquisition_execution_lock_key").fetchone()
    with ThreadPoolExecutor(max_workers=2) as executor:
        observed = tuple(
            executor.map(lambda _: first_catalog.acquisition_execution_active(first.acquisition_id), range(2))
        )
    with psycopg.connect(postgres_dsn) as connection:
        after = connection.execute("SELECT count(*) FROM market_acquisition_execution_lock_key").fetchone()
    assert observed == (False, False)
    assert before == after

    owner = first_catalog.try_acquire_acquisition_execution(first.acquisition_id)
    non_owner = second_catalog.try_acquire_acquisition_execution(first.acquisition_id)
    independent = second_catalog.try_acquire_acquisition_execution(second.acquisition_id)
    try:
        assert owner.acquired
        assert not non_owner.acquired
        assert independent.acquired
        with ThreadPoolExecutor(max_workers=2) as executor:
            assert tuple(
                executor.map(lambda _: second_catalog.acquisition_execution_active(first.acquisition_id), range(2))
            ) == (True, True)
        assert owner._connection is not None
        with psycopg.connect(postgres_dsn) as connection:
            state = connection.execute(
                "SELECT state FROM pg_stat_activity WHERE pid=%s", (owner._connection.info.backend_pid,)
            ).fetchone()
        assert state == ("idle",)
        assert second_catalog.latest_acquisition_attempt(first.acquisition_id) is None
    finally:
        non_owner.close()
        independent.close()
        owner.close()

    assert not second_catalog.acquisition_execution_active(first.acquisition_id)

    retry = second_catalog.try_acquire_acquisition_execution(first.acquisition_id)
    try:
        assert retry.acquired
        assert not first_catalog.acquisition_execution_active(second.acquisition_id)
    finally:
        retry.close()


def test_current_range_lookup_loads_manifest_and_has_exact_family_index(postgres_dsn: str, tmp_path: Path) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    wal, segment, _ = _sealed(tmp_path / "range", lambda: BASE, kind="BAR")
    records = wal.read_sealed(segment.segment_id)
    store = OnlyInMemoryMarketFactStore()
    store.write_segment(segment, records)
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    manifest, revision, _ = OnlyRevisionCommitService(store, catalog, now=lambda: BASE).commit(
        segment, _scope("BAR"), {segment.segment_id: records}
    )

    superseding_manifest = OnlyCoverageManifest.build(
        revision.scope,
        manifest.segment_refs,
        coverage_status=OnlyCoverageStatus.COMPLETE,
        proof=manifest.proof + ("superseding=true",),
    )
    superseding_revision = OnlyMarketDataRevision.build(
        superseding_manifest,
        normalizers=revision.normalizers,
        creation_reason="REPAIR",
        parent_revision_id=revision.revision_id,
    )
    superseding_seal = only_build_seal(
        superseding_revision, superseding_manifest, sealed_at=BASE + timedelta(seconds=1)
    )
    catalog.commit_revision((segment,), superseding_manifest, superseding_revision, superseding_seal)

    family = OnlyMarketDataRangeFamily.from_scope(revision.scope)
    assert catalog.list_current_sealed_revisions_overlapping(
        family, revision.scope.start_ns, revision.scope.end_ns
    ) == (superseding_revision,)
    assert (
        catalog.list_current_sealed_revisions_overlapping(family, revision.scope.end_ns, revision.scope.end_ns + 1)
        == ()
    )
    assert catalog.load_coverage_manifest(superseding_manifest.manifest_id) == superseding_manifest

    with psycopg.connect(postgres_dsn) as connection:
        definition = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname='market_data_revision_range_family_overlap_idx'"
        ).fetchone()
        connection.execute("SET LOCAL enable_seqscan=off")
        plan = connection.execute(
            "EXPLAIN (COSTS OFF) SELECT revision_id FROM market_latest_sealed_revision "
            "WHERE scope->>'source_id'=%s AND scope->>'market'=%s AND scope->>'instrument_id'=%s "
            "AND scope->>'data_kind'=%s AND scope->>'data_version'=%s "
            "AND scope->>'bar_type' IS NOT DISTINCT FROM %s "
            "AND scope#>>'{bar_construction,fingerprint}' IS NOT DISTINCT FROM %s "
            "AND (scope->>'start_ns')::BIGINT < %s AND (scope->>'end_ns')::BIGINT > %s",
            (
                family.source_id,
                family.market,
                family.instrument_id,
                family.data_kind,
                family.data_version,
                family.bar_type,
                family.bar_construction.fingerprint if family.bar_construction is not None else None,
                revision.scope.end_ns,
                revision.scope.start_ns,
            ),
        ).fetchall()
    assert definition is not None
    assert all(
        token in definition[0]
        for token in (
            "source_id",
            "market",
            "instrument_id",
            "data_kind",
            "data_version",
            "bar_type",
            "fingerprint",
            "start_ns",
            "end_ns",
        )
    )
    assert "market_data_revision_range_family_overlap_idx" in "\n".join(row[0] for row in plan)
