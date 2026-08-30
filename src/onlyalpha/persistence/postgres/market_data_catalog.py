"""PostgreSQL append-only Market Data Revision catalog."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from onlyalpha.canonical import only_canonical_payload
from onlyalpha.market_data.durable.models import (
    OnlyCoverageManifest,
    OnlyIngestSegment,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSeal,
)

from .config import OnlyPostgresConfig
from .migration import OnlyPostgresSchemaVerifier


class OnlyPostgresMarketDataCatalog:
    def __init__(self, dsn: str) -> None:
        OnlyPostgresSchemaVerifier(dsn).assert_compatible()
        self._dsn = OnlyPostgresConfig(dsn).operational_dsn()

    def commit_revision(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        manifest: OnlyCoverageManifest,
        revision: OnlyMarketDataRevision,
        seal: OnlyMarketDataSeal,
    ) -> None:
        scope = json.dumps(only_canonical_payload(manifest.scope), sort_keys=True, separators=(",", ":"))
        now = seal.sealed_at
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                for segment in segments:
                    self._ensure_source_and_session(connection, segment, now)
                    self._insert_segment(connection, segment)
                    connection.execute(
                        "INSERT INTO market_segment_state_event(event_id,segment_id,state,occurred_at,detail) "
                        "VALUES (%s,%s,'VERIFIED',%s,'{}') ON CONFLICT DO NOTHING",
                        (f"{segment.segment_id}:VERIFIED", segment.segment_id, now),
                    )
                connection.execute(
                    "INSERT INTO market_coverage_manifest "
                    "(manifest_id,manifest_fingerprint,scope,complete,proof,issues,created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        manifest.manifest_id,
                        manifest.fingerprint,
                        scope,
                        manifest.complete,
                        json.dumps(manifest.proof),
                        json.dumps(manifest.issues),
                        now,
                    ),
                )
                for ordinal, (segment_id, content_hash) in enumerate(manifest.segment_refs):
                    connection.execute(
                        "INSERT INTO market_coverage_manifest_segment "
                        "(manifest_id,ordinal,segment_id,segment_content_hash) VALUES (%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING",
                        (manifest.manifest_id, ordinal, segment_id, content_hash),
                    )
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
                for segment in segments:
                    connection.execute(
                        "INSERT INTO market_segment_state_event(event_id,segment_id,state,occurred_at,detail) "
                        "VALUES (%s,%s,'COMMITTED',%s,%s) ON CONFLICT DO NOTHING",
                        (
                            f"{segment.segment_id}:COMMITTED",
                            segment.segment_id,
                            now,
                            json.dumps({"revision_id": revision.revision_id}),
                        ),
                    )
                self._assert_exact(connection, segments, manifest, revision, seal)

    def is_segment_committed(self, segment_id: str, content_hash: str) -> bool:
        with psycopg.connect(self._dsn) as connection:
            row = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM market_ingest_segment s JOIN market_segment_state_event e "
                "ON e.segment_id=s.segment_id AND e.state='COMMITTED' WHERE s.segment_id=%s AND s.content_hash=%s)",
                (segment_id, content_hash),
            ).fetchone()
        return bool(row and row[0])

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
            "(segment_id,capture_session_id,source_id,market,stream,schema_version,record_count,raw_count,"
            "canonical_count,content_hash,created_at,sealed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (
                segment.segment_id,
                segment.capture_session_id,
                segment.source_id,
                segment.market,
                segment.stream,
                segment.schema_version,
                segment.record_count,
                segment.raw_count,
                segment.canonical_count,
                segment.content_hash,
                segment.created_at,
                segment.sealed_at,
            ),
        )

    @staticmethod
    def _assert_exact(
        connection: psycopg.Connection[dict[str, object]],
        segments: tuple[OnlyIngestSegment, ...],
        manifest: OnlyCoverageManifest,
        revision: OnlyMarketDataRevision,
        seal: OnlyMarketDataSeal,
    ) -> None:
        segment_rows = connection.execute(
            "SELECT segment_id,capture_session_id,source_id,market,stream,schema_version,record_count,raw_count,"
            "canonical_count,content_hash,created_at,sealed_at FROM market_ingest_segment "
            "WHERE segment_id = ANY(%s) ORDER BY segment_id",
            ([segment.segment_id for segment in segments],),
        ).fetchall()
        expected_segments = tuple(sorted(segments, key=lambda item: item.segment_id))
        actual_segments = tuple(
            (
                str(row["segment_id"]),
                str(row["capture_session_id"]),
                str(row["source_id"]),
                str(row["market"]),
                str(row["stream"]),
                int(str(row["schema_version"])),
                int(str(row["record_count"])),
                int(str(row["raw_count"])),
                int(str(row["canonical_count"])),
                str(row["content_hash"]),
                row["created_at"],
                row["sealed_at"],
            )
            for row in segment_rows
        )
        expected_segment_values = tuple(
            (
                segment.segment_id,
                segment.capture_session_id,
                segment.source_id,
                segment.market,
                segment.stream,
                segment.schema_version,
                segment.record_count,
                segment.raw_count,
                segment.canonical_count,
                segment.content_hash,
                segment.created_at,
                segment.sealed_at,
            )
            for segment in expected_segments
        )
        manifest_row = connection.execute(
            "SELECT manifest_fingerprint,scope,complete,proof,issues FROM market_coverage_manifest "
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
            actual_segments != expected_segment_values
            or manifest_row is None
            or (
                str(manifest_row["manifest_fingerprint"]),
                manifest_row["scope"],
                bool(manifest_row["complete"]),
                _string_tuple(manifest_row["proof"]),
                _string_tuple(manifest_row["issues"]),
            )
            != (manifest.fingerprint, expected_scope, manifest.complete, manifest.proof, manifest.issues)
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
