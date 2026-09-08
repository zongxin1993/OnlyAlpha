"""PostgreSQL append-only Market Data Revision catalog."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from onlyalpha.canonical import only_canonical_payload
from onlyalpha.core.clock import only_system_utc_now
from onlyalpha.market_data.durable.models import (
    OnlyCoverageManifest,
    OnlyCoverageStatus,
    OnlyIngestSegment,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataProvenance,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSeal,
)

from .config import OnlyPostgresConfig
from .migration import OnlyPostgresSchemaVerifier
from .version import only_assert_supported_postgres_server


class OnlyPostgresMarketDataCatalog:
    def __init__(self, dsn: str, *, now: Callable[[], datetime] = only_system_utc_now) -> None:
        only_assert_supported_postgres_server(dsn)
        OnlyPostgresSchemaVerifier(dsn).assert_compatible()
        self._dsn = OnlyPostgresConfig(dsn).operational_dsn()
        self._now = now

    @classmethod
    def _legacy_upgrade_test_source(
        cls, dsn: str, *, now: Callable[[], datetime] = only_system_utc_now
    ) -> OnlyPostgresMarketDataCatalog:
        """Construct only the isolated PostgreSQL 16 logical-upgrade test source."""
        OnlyPostgresSchemaVerifier(dsn).assert_compatible()
        value = cls.__new__(cls)
        value._dsn = OnlyPostgresConfig(dsn).operational_dsn()
        value._now = now
        return value

    def commit_durable_segments(self, segments: tuple[OnlyIngestSegment, ...]) -> None:
        if not segments or len({item.segment_id for item in segments}) != len(segments):
            raise ValueError("POSTGRES_DURABLE_SEGMENT_SET_INVALID")
        ordered = tuple(sorted(segments, key=lambda item: item.segment_id))
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                for segment in ordered:
                    self._ensure_source_and_session(connection, segment, segment.sealed_at)
                    self._insert_segment(connection, segment)
                    connection.execute(
                        "INSERT INTO market_segment_state_event(event_id,segment_id,state,occurred_at,detail) "
                        "VALUES (%s,%s,'DURABLE_SEGMENT_COMMITTED',%s,%s) ON CONFLICT DO NOTHING",
                        (
                            f"{segment.segment_id}:DURABLE_SEGMENT_COMMITTED",
                            segment.segment_id,
                            segment.sealed_at,
                            json.dumps({"content_hash": segment.content_hash}),
                        ),
                    )
                self._assert_segments_exact(connection, ordered)

    def commit_acquisition_intent(self, intent: OnlyMarketDataAcquisitionIntent) -> None:
        scope = json.dumps(only_canonical_payload(intent.requested_scope), sort_keys=True, separators=(",", ":"))
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                connection.execute(
                    "INSERT INTO market_acquisition_intent "
                    "(acquisition_id,request_fingerprint,source_id,requested_scope,provenance,created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        intent.acquisition_id,
                        intent.request_fingerprint,
                        intent.source_id,
                        scope,
                        intent.provenance.value,
                        intent.created_at,
                    ),
                )
                row = connection.execute(
                    "SELECT request_fingerprint,source_id,requested_scope,provenance,created_at "
                    "FROM market_acquisition_intent WHERE acquisition_id=%s",
                    (intent.acquisition_id,),
                ).fetchone()
                if row is None or (
                    str(row["request_fingerprint"]),
                    str(row["source_id"]),
                    row["requested_scope"],
                    str(row["provenance"]),
                    row["created_at"],
                ) != (
                    intent.request_fingerprint,
                    intent.source_id,
                    only_canonical_payload(intent.requested_scope),
                    intent.provenance.value,
                    intent.created_at,
                ):
                    raise RuntimeError("POSTGRES_ACQUISITION_INTENT_CONFLICT")

    def commit_coverage_manifest(self, manifest: OnlyCoverageManifest) -> None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                self._insert_manifest(connection, manifest, self._now())

    def commit_revision(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        manifest: OnlyCoverageManifest,
        revision: OnlyMarketDataRevision,
        seal: OnlyMarketDataSeal,
    ) -> None:
        if manifest.coverage_status is not OnlyCoverageStatus.COMPLETE:
            raise RuntimeError("POSTGRES_REVISION_REQUIRES_COMPLETE_COVERAGE")
        scope = json.dumps(only_canonical_payload(manifest.scope), sort_keys=True, separators=(",", ":"))
        now = seal.sealed_at
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                for segment in segments:
                    if not self._is_segment_committed(connection, segment.segment_id, segment.content_hash):
                        raise RuntimeError("POSTGRES_REVISION_REFERENCES_NON_DURABLE_SEGMENT")
                self._insert_manifest(connection, manifest, now)
                connection.execute(
                    "INSERT INTO market_data_revision "
                    "(revision_id,revision_fingerprint,manifest_id,scope,parent_revision_id,normalizers,creation_reason,created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        revision.revision_id,
                        revision.fingerprint,
                        revision.manifest_id,
                        scope,
                        revision.parent_revision_id,
                        json.dumps(revision.normalizers),
                        revision.creation_reason,
                        now,
                    ),
                )
                for ordinal, (segment_id, content_hash) in enumerate(revision.segment_refs):
                    connection.execute(
                        "INSERT INTO market_revision_segment "
                        "(revision_id,ordinal,segment_id,segment_content_hash) VALUES (%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING",
                        (revision.revision_id, ordinal, segment_id, content_hash),
                    )
                connection.execute(
                    "INSERT INTO market_revision_seal "
                    "(seal_id,revision_id,revision_fingerprint,checks,sealed_at) VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    (
                        seal.seal_id,
                        seal.revision_id,
                        seal.revision_fingerprint,
                        json.dumps(seal.checks),
                        seal.sealed_at,
                    ),
                )
                self._assert_exact(connection, segments, manifest, revision, seal)

    def is_segment_committed(self, segment_id: str, content_hash: str) -> bool:
        with psycopg.connect(self._dsn) as connection:
            row = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM market_ingest_segment s JOIN market_segment_state_event e "
                "ON e.segment_id=s.segment_id AND e.state IN ('DURABLE_SEGMENT_COMMITTED','COMMITTED') "
                "WHERE s.segment_id=%s AND s.content_hash=%s)",
                (segment_id, content_hash),
            ).fetchone()
        return bool(row and row[0])

    def load_durable_segments(self, segment_ids: tuple[str, ...]) -> tuple[OnlyIngestSegment, ...]:
        if not segment_ids:
            return ()
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                self._segment_select() + " WHERE segment_id = ANY(%s) ORDER BY array_position(%s, segment_id)",
                (list(segment_ids), list(segment_ids)),
            ).fetchall()
        segments = tuple(self._segment(row) for row in rows)
        if tuple(item.segment_id for item in segments) != segment_ids:
            raise KeyError("DURABLE_SEGMENT_NOT_FOUND")
        return segments

    def list_durable_segments(self, scope: OnlyMarketDataScope) -> tuple[OnlyIngestSegment, ...]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                self._segment_select()
                + " WHERE source_id=%s AND market=%s AND instrument_id=%s AND data_kind=%s AND data_version=%s "
                "AND bar_type IS NOT DISTINCT FROM %s AND start_ns < %s AND end_ns > %s ORDER BY segment_id",
                (
                    scope.source_id,
                    scope.market,
                    scope.instrument_id,
                    scope.data_kind,
                    scope.data_version,
                    scope.bar_type,
                    scope.end_ns,
                    scope.start_ns,
                ),
            ).fetchall()
        return tuple(self._segment(row) for row in rows)

    def load_sealed_revision(self, revision_id: str) -> tuple[OnlyMarketDataRevision, OnlyMarketDataSeal]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT r.*, s.seal_id, s.checks, s.sealed_at, s.revision_fingerprint AS sealed_fingerprint "
                "FROM market_data_revision r JOIN market_revision_seal s USING(revision_id) WHERE revision_id=%s",
                (revision_id,),
            ).fetchone()
            refs = connection.execute(
                "SELECT segment_id,segment_content_hash FROM market_revision_segment "
                "WHERE revision_id=%s ORDER BY ordinal",
                (revision_id,),
            ).fetchall()
        if row is None:
            raise KeyError("SEALED_REVISION_NOT_FOUND")
        scope = _scope(row["scope"])
        revision = OnlyMarketDataRevision(
            str(row["revision_id"]),
            scope,
            str(row["manifest_id"]),
            tuple((str(item["segment_id"]), str(item["segment_content_hash"])) for item in refs),
            tuple((str(item[0]), str(item[1])) for item in row["normalizers"]),
            None if row["parent_revision_id"] is None else str(row["parent_revision_id"]),
            str(row["creation_reason"]),
            str(row["revision_fingerprint"]),
        )
        seal = OnlyMarketDataSeal(
            str(row["seal_id"]),
            revision.revision_id,
            str(row["sealed_fingerprint"]),
            tuple(str(item) for item in row["checks"]),
            row["sealed_at"],
        )
        return revision, seal

    def latest_sealed_revision(self, scope: OnlyMarketDataScope) -> OnlyMarketDataRevision:
        payload = json.dumps(only_canonical_payload(scope), sort_keys=True, separators=(",", ":"))
        with psycopg.connect(self._dsn) as connection:
            row = connection.execute(
                "SELECT revision_id FROM market_latest_sealed_revision WHERE scope=%s", (payload,)
            ).fetchone()
        if row is None:
            raise KeyError("SEALED_REVISION_NOT_FOUND")
        return self.load_sealed_revision(str(row[0]))[0]

    @staticmethod
    def _is_segment_committed(
        connection: psycopg.Connection[dict[str, object]], segment_id: str, content_hash: str
    ) -> bool:
        row = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM market_ingest_segment s JOIN market_segment_state_event e "
            "ON e.segment_id=s.segment_id AND e.state IN ('DURABLE_SEGMENT_COMMITTED','COMMITTED') "
            "WHERE s.segment_id=%s AND s.content_hash=%s) AS committed",
            (segment_id, content_hash),
        ).fetchone()
        return bool(row and row["committed"])

    @staticmethod
    def _insert_manifest(
        connection: psycopg.Connection[dict[str, object]], manifest: OnlyCoverageManifest, created_at: datetime
    ) -> None:
        scope = json.dumps(only_canonical_payload(manifest.scope), sort_keys=True, separators=(",", ":"))
        gaps = json.dumps(
            [only_canonical_payload(item) for item in manifest.gaps], sort_keys=True, separators=(",", ":")
        )
        connection.execute(
            "INSERT INTO market_coverage_manifest "
            "(manifest_id,manifest_fingerprint,scope,complete,coverage_status,proof,issues,gaps,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                manifest.manifest_id,
                manifest.fingerprint,
                scope,
                manifest.complete,
                manifest.coverage_status.value,
                json.dumps(manifest.proof),
                json.dumps(manifest.issues),
                gaps,
                created_at,
            ),
        )
        for ordinal, (segment_id, content_hash) in enumerate(manifest.segment_refs):
            connection.execute(
                "INSERT INTO market_coverage_manifest_segment "
                "(manifest_id,ordinal,segment_id,segment_content_hash) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (manifest.manifest_id, ordinal, segment_id, content_hash),
            )
        row = connection.execute(
            "SELECT manifest_fingerprint,scope,complete,coverage_status,proof,issues,gaps "
            "FROM market_coverage_manifest WHERE manifest_id=%s",
            (manifest.manifest_id,),
        ).fetchone()
        refs = connection.execute(
            "SELECT segment_id,segment_content_hash FROM market_coverage_manifest_segment "
            "WHERE manifest_id=%s ORDER BY ordinal",
            (manifest.manifest_id,),
        ).fetchall()
        if row is None or (
            str(row["manifest_fingerprint"]),
            row["scope"],
            bool(row["complete"]),
            str(row["coverage_status"]),
            _string_tuple(row["proof"]),
            _string_tuple(row["issues"]),
            row["gaps"],
            tuple((str(item["segment_id"]), str(item["segment_content_hash"])) for item in refs),
        ) != (
            manifest.fingerprint,
            only_canonical_payload(manifest.scope),
            manifest.complete,
            manifest.coverage_status.value,
            manifest.proof,
            manifest.issues,
            [only_canonical_payload(item) for item in manifest.gaps],
            manifest.segment_refs,
        ):
            raise RuntimeError("POSTGRES_COVERAGE_MANIFEST_CONFLICT")

    @staticmethod
    def _segment_select() -> str:
        return (
            "SELECT segment_id,capture_session_id,source_id,market,stream,provider,venue,capture_mode,"
            "provider_schema,codec,schema_version,record_count,raw_count,canonical_count,content_hash,"
            "created_at,sealed_at,instrument_id,data_kind,start_ns,end_ns,data_version,bar_type,"
            "first_sequence,last_sequence FROM market_ingest_segment"
        )

    @staticmethod
    def _segment(row: Mapping[str, object]) -> OnlyIngestSegment:
        return OnlyIngestSegment(
            str(row["segment_id"]),
            str(row["capture_session_id"]),
            str(row["source_id"]),
            str(row["market"]),
            str(row["stream"]),
            str(row["provider"]),
            str(row["venue"]),
            OnlyMarketDataProvenance(str(row["capture_mode"])),
            str(row["provider_schema"]),
            str(row["codec"]),
            int(str(row["schema_version"])),
            int(str(row["record_count"])),
            int(str(row["raw_count"])),
            int(str(row["canonical_count"])),
            str(row["content_hash"]),
            row["created_at"],  # type: ignore[arg-type]
            row["sealed_at"],  # type: ignore[arg-type]
            None if row["instrument_id"] is None else str(row["instrument_id"]),
            None if row["data_kind"] is None else str(row["data_kind"]),
            None if row["start_ns"] is None else int(str(row["start_ns"])),
            None if row["end_ns"] is None else int(str(row["end_ns"])),
            None if row["data_version"] is None else str(row["data_version"]),
            None if row["bar_type"] is None else str(row["bar_type"]),
            None if row["first_sequence"] is None else int(str(row["first_sequence"])),
            None if row["last_sequence"] is None else int(str(row["last_sequence"])),
        )

    @staticmethod
    def _ensure_source_and_session(
        connection: psycopg.Connection[dict[str, object]], segment: OnlyIngestSegment, now: datetime
    ) -> None:
        connection.execute(
            "INSERT INTO market_source(source_id,provider,venue,market,schema_version) "
            "VALUES (%s,%s,%s,%s,1) ON CONFLICT DO NOTHING",
            (segment.source_id, segment.provider, segment.venue, segment.market),
        )
        connection.execute(
            "INSERT INTO market_capture_session "
            "(capture_session_id,source_id,capture_mode,provider_schema,codec,started_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                segment.capture_session_id,
                segment.source_id,
                segment.capture_mode.value,
                segment.provider_schema,
                segment.codec,
                segment.created_at,
            ),
        )
        source = connection.execute(
            "SELECT provider,venue,market FROM market_source WHERE source_id=%s",
            (segment.source_id,),
        ).fetchone()
        session = connection.execute(
            "SELECT source_id,capture_mode,provider_schema,codec,started_at "
            "FROM market_capture_session WHERE capture_session_id=%s",
            (segment.capture_session_id,),
        ).fetchone()
        if source is None or tuple(map(str, source.values())) != (
            segment.provider,
            segment.venue,
            segment.market,
        ):
            raise RuntimeError("POSTGRES_MARKET_SOURCE_CONFLICT")
        if session is None or (
            str(session["source_id"]),
            str(session["capture_mode"]),
            str(session["provider_schema"]),
            str(session["codec"]),
            session["started_at"],
        ) != (
            segment.source_id,
            segment.capture_mode.value,
            segment.provider_schema,
            segment.codec,
            segment.created_at,
        ):
            raise RuntimeError("POSTGRES_CAPTURE_SESSION_CONFLICT")

    @staticmethod
    def _insert_segment(connection: psycopg.Connection[dict[str, object]], segment: OnlyIngestSegment) -> None:
        connection.execute(
            "INSERT INTO market_ingest_segment "
            "(segment_id,capture_session_id,source_id,market,stream,provider,venue,capture_mode,provider_schema,codec,"
            "schema_version,record_count,raw_count,canonical_count,content_hash,created_at,sealed_at,instrument_id,"
            "data_kind,start_ns,end_ns,data_version,bar_type,first_sequence,last_sequence) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (
                segment.segment_id,
                segment.capture_session_id,
                segment.source_id,
                segment.market,
                segment.stream,
                segment.provider,
                segment.venue,
                segment.capture_mode.value,
                segment.provider_schema,
                segment.codec,
                segment.schema_version,
                segment.record_count,
                segment.raw_count,
                segment.canonical_count,
                segment.content_hash,
                segment.created_at,
                segment.sealed_at,
                segment.instrument_id,
                segment.data_kind,
                segment.start_ns,
                segment.end_ns,
                segment.data_version,
                segment.bar_type,
                segment.first_sequence,
                segment.last_sequence,
            ),
        )

    @staticmethod
    def _assert_segments_exact(
        connection: psycopg.Connection[dict[str, object]], segments: tuple[OnlyIngestSegment, ...]
    ) -> None:
        rows = connection.execute(
            OnlyPostgresMarketDataCatalog._segment_select() + " WHERE segment_id = ANY(%s) ORDER BY segment_id",
            ([segment.segment_id for segment in segments],),
        ).fetchall()
        actual = tuple(OnlyPostgresMarketDataCatalog._segment(row) for row in rows)
        expected = tuple(sorted(segments, key=lambda item: item.segment_id))
        if actual != expected or any(
            not OnlyPostgresMarketDataCatalog._is_segment_committed(
                connection, segment.segment_id, segment.content_hash
            )
            for segment in expected
        ):
            raise RuntimeError("POSTGRES_DURABLE_SEGMENT_COMMIT_CONFLICT")

    @staticmethod
    def _assert_exact(
        connection: psycopg.Connection[dict[str, object]],
        segments: tuple[OnlyIngestSegment, ...],
        manifest: OnlyCoverageManifest,
        revision: OnlyMarketDataRevision,
        seal: OnlyMarketDataSeal,
    ) -> None:
        OnlyPostgresMarketDataCatalog._assert_segments_exact(connection, segments)
        manifest_row = connection.execute(
            "SELECT manifest_fingerprint,scope,complete,coverage_status,proof,issues,gaps "
            "FROM market_coverage_manifest "
            "WHERE manifest_id=%s",
            (manifest.manifest_id,),
        ).fetchone()
        revision_row = connection.execute(
            "SELECT revision_fingerprint,manifest_id,scope,parent_revision_id,normalizers,creation_reason "
            "FROM market_data_revision WHERE revision_id=%s",
            (revision.revision_id,),
        ).fetchone()
        manifest_segment_rows = connection.execute(
            "SELECT segment_id,segment_content_hash FROM market_coverage_manifest_segment "
            "WHERE manifest_id=%s ORDER BY ordinal",
            (manifest.manifest_id,),
        ).fetchall()
        revision_segment_rows = connection.execute(
            "SELECT segment_id,segment_content_hash FROM market_revision_segment WHERE revision_id=%s ORDER BY ordinal",
            (revision.revision_id,),
        ).fetchall()
        seal_row = connection.execute(
            "SELECT seal_id,revision_fingerprint,checks,sealed_at FROM market_revision_seal WHERE revision_id=%s",
            (revision.revision_id,),
        ).fetchone()
        actual_manifest_refs = tuple(
            (str(row["segment_id"]), str(row["segment_content_hash"])) for row in manifest_segment_rows
        )
        actual_revision_refs = tuple(
            (str(row["segment_id"]), str(row["segment_content_hash"])) for row in revision_segment_rows
        )
        expected_scope = only_canonical_payload(manifest.scope)
        if (
            manifest_row is None
            or (
                str(manifest_row["manifest_fingerprint"]),
                manifest_row["scope"],
                bool(manifest_row["complete"]),
                str(manifest_row["coverage_status"]),
                _string_tuple(manifest_row["proof"]),
                _string_tuple(manifest_row["issues"]),
                manifest_row["gaps"],
            )
            != (
                manifest.fingerprint,
                expected_scope,
                manifest.complete,
                manifest.coverage_status.value,
                manifest.proof,
                manifest.issues,
                [only_canonical_payload(item) for item in manifest.gaps],
            )
            or revision_row is None
            or (
                str(revision_row["revision_fingerprint"]),
                str(revision_row["manifest_id"]),
                revision_row["scope"],
                None if revision_row["parent_revision_id"] is None else str(revision_row["parent_revision_id"]),
                _pair_tuple(revision_row["normalizers"]),
                str(revision_row["creation_reason"]),
            )
            != (
                revision.fingerprint,
                revision.manifest_id,
                expected_scope,
                revision.parent_revision_id,
                revision.normalizers,
                revision.creation_reason,
            )
            or actual_manifest_refs != manifest.segment_refs
            or actual_revision_refs != revision.segment_refs
            or seal_row is None
            or (
                str(seal_row["seal_id"]),
                str(seal_row["revision_fingerprint"]),
                _string_tuple(seal_row["checks"]),
                seal_row["sealed_at"],
            )
            != (seal.seal_id, seal.revision_fingerprint, seal.checks, seal.sealed_at)
        ):
            raise RuntimeError("POSTGRES_MARKET_DATA_COMMIT_CONFLICT")


def _scope(value: object) -> OnlyMarketDataScope:
    if not isinstance(value, Mapping):
        raise ValueError("MARKET_DATA_SCOPE_INVALID")
    return OnlyMarketDataScope(
        str(value["source_id"]),
        str(value["market"]),
        str(value["instrument_id"]),
        str(value["data_kind"]),
        int(str(value["start_ns"])),
        int(str(value["end_ns"])),
        str(value["data_version"]),
        None if value.get("bar_type") is None else str(value["bar_type"]),
        None if value.get("first_sequence") is None else int(str(value["first_sequence"])),
        None if value.get("last_sequence") is None else int(str(value["last_sequence"])),
    )


def _string_tuple(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    return tuple(str(item) for item in value)


def _pair_tuple(value: object) -> tuple[tuple[str, str], ...] | None:
    if not isinstance(value, list):
        return None
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            return None
        result.append((str(item[0]), str(item[1])))
    return tuple(result)


__all__ = ["OnlyPostgresMarketDataCatalog"]
