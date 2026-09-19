"""PostgreSQL Research source-history store's transactional closed-cut readers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast

import psycopg
from psycopg.rows import dict_row

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.source_cut import (
    OnlySourceClosedCutV1,
    OnlySourceCutEntryV1,
    OnlySourceCutError,
    OnlySourceObservationV1,
)

from .research_execution_store import _decode_attempt
from .research_run_store import OnlyPostgresResearchRunStore

_FAMILIES = frozenset(
    {
        "RESEARCH_RUN",
        "RESEARCH_ATTEMPT",
        "PRODUCT_COMMAND_ADMISSION",
        "PRODUCT_COMMAND_RECEIPT",
    }
)
_DATETIME_FIELDS = frozenset(
    {
        "queued_at",
        "started_at",
        "cancel_requested_at",
        "finished_at",
        "claimed_at",
        "last_heartbeat_at",
        "lease_expires_at",
        "accepted_at",
    }
)


class OnlyPostgresResearchSourceCutAuthority:
    """Source-owned journal and cut tables; no Memory or Product authority is granted."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def for_family(self, source_family: str) -> OnlyPostgresResearchFamilyCutReader:
        self._require_family(source_family)
        return OnlyPostgresResearchFamilyCutReader(self, source_family)

    def capture_closed_cut(self, source_family: str) -> OnlySourceClosedCutV1:
        self._require_family(source_family)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                # The trigger updates this row in the same transaction as every
                # source mutation. FOR UPDATE is the capture linearization point.
                row = cast(
                    Mapping[str, object] | None,
                    connection.execute(
                        "SELECT last_index FROM research_source_history_frontier WHERE singleton = TRUE FOR UPDATE"
                    ).fetchone(),
                )
                if row is None:
                    raise OnlySourceCutError("SOURCE_CUT_FRONTIER_MISSING")
                frontier = int(cast(int, row["last_index"]))
                cut = self._derive(connection, source_family, frontier)
                connection.execute(
                    "INSERT INTO research_source_closed_cut "
                    "(cut_fingerprint, source_family, frontier, canonical_document, schema_version) "
                    "VALUES (%s, %s, %s, %s, 1) ON CONFLICT (cut_fingerprint) DO NOTHING",
                    (cut.cut_fingerprint, source_family, frontier, only_canonical_json(cut.to_dict())),
                )
                self._load_in_transaction(connection, cut.cut_fingerprint, source_family)
            return cut
        except psycopg.Error as exc:
            raise OnlySourceCutError("SOURCE_CUT_POSTGRES_UNAVAILABLE") from exc

    def load_closed_cut_verified(self, fingerprint: str, source_family: str) -> OnlySourceClosedCutV1:
        self._require_family(source_family)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                return self._load_in_transaction(connection, fingerprint, source_family)
        except psycopg.Error as exc:
            raise OnlySourceCutError("SOURCE_CUT_POSTGRES_UNAVAILABLE") from exc

    def iter_closed_cut_observations_verified(
        self, fingerprint: str, source_family: str
    ) -> tuple[OnlySourceObservationV1, ...]:
        """Return the exact historical events, never current mutable Run/Receipt rows."""
        self._require_family(source_family)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                cut = self._load_in_transaction(connection, fingerprint, source_family)
                observations: list[OnlySourceObservationV1] = []
                for entry in cut.entries:
                    event_index = int(entry.locator)
                    row = cast(
                        Mapping[str, object] | None,
                        connection.execute(
                            "SELECT event_index, source_family, native_locator, source_row, operation, schema_version "
                            "FROM research_source_history WHERE event_index = %s",
                            (event_index,),
                        ).fetchone(),
                    )
                    if row is None:
                        raise OnlySourceCutError("SOURCE_OBSERVATION_UNAVAILABLE")
                    self._verify_history_row(row)
                    payload: dict[str, object] = {
                        "schema_version": 1,
                        "source_family": source_family,
                        "native_locator": row["native_locator"],
                        "source_row": row["source_row"],
                        "operation": row["operation"],
                        "event_index": event_index,
                    }
                    if (
                        row["event_index"] != event_index
                        or row["source_family"] != source_family
                        or row["schema_version"] != 1
                        or only_canonical_fingerprint(payload) != entry.content_fingerprint
                        or entry.identity != entry.content_fingerprint
                    ):
                        raise OnlySourceCutError("SOURCE_OBSERVATION_MISMATCH")
                    observations.append(
                        OnlySourceObservationV1(
                            source_family,
                            cut.source_schema_version,
                            fingerprint,
                            entry.locator,
                            entry.identity,
                            entry.content_fingerprint,
                            payload,
                        )
                    )
                return tuple(observations)
        except psycopg.Error as exc:
            raise OnlySourceCutError("SOURCE_CUT_POSTGRES_UNAVAILABLE") from exc

    def _load_in_transaction(
        self, connection: psycopg.Connection[object], fingerprint: str, family: str
    ) -> OnlySourceClosedCutV1:
        row = cast(
            Mapping[str, object] | None,
            connection.execute(
                "SELECT source_family, frontier, canonical_document, schema_version "
                "FROM research_source_closed_cut WHERE cut_fingerprint = %s",
                (fingerprint,),
            ).fetchone(),
        )
        if row is None:
            raise OnlySourceCutError("SOURCE_CUT_NOT_FOUND")
        try:
            raw = str(row["canonical_document"])
            document = json.loads(raw)
            if not isinstance(document, dict) or raw != only_canonical_json(document) or row["schema_version"] != 1:
                raise ValueError("non-canonical cut")
            cut = OnlySourceClosedCutV1.from_dict(document)
            if cut.cut_fingerprint != fingerprint or cut.source_family != family or row["source_family"] != family:
                raise ValueError("cut identity mismatch")
            if cut.cut_boundary != f"JOURNAL_INDEX:{row['frontier']}":
                raise ValueError("frontier mismatch")
            if self._derive(connection, family, int(cast(int, row["frontier"]))) != cut:
                raise ValueError("source historical cut mismatch")
            return cut
        except (ValueError, TypeError, KeyError, OnlySourceCutError) as exc:
            raise OnlySourceCutError("SOURCE_CUT_CORRUPT") from exc

    def _derive(self, connection: psycopg.Connection[object], family: str, frontier: int) -> OnlySourceClosedCutV1:
        if frontier < 0:
            raise OnlySourceCutError("SOURCE_CUT_FRONTIER_INVALID")
        rows = cast(
            list[Mapping[str, object]],
            connection.execute(
                "SELECT event_index, source_family, native_locator, source_row, operation, schema_version "
                "FROM research_source_history WHERE event_index <= %s ORDER BY event_index",
                (frontier,),
            ).fetchall(),
        )
        if len(rows) != frontier:
            raise OnlySourceCutError("SOURCE_CUT_JOURNAL_GAP")
        entries: list[OnlySourceCutEntryV1] = []
        for expected_index, row in enumerate(rows, start=1):
            if row["event_index"] != expected_index or row["schema_version"] != 1:
                raise OnlySourceCutError("SOURCE_CUT_JOURNAL_GAP")
            self._verify_history_row(row)
            if row["source_family"] == family:
                content = only_canonical_fingerprint(
                    {
                        "schema_version": 1,
                        "source_family": family,
                        "native_locator": row["native_locator"],
                        "source_row": row["source_row"],
                        "operation": row["operation"],
                        "event_index": expected_index,
                    }
                )
                entries.append(OnlySourceCutEntryV1(f"{expected_index:020d}", content, content))
        return OnlySourceClosedCutV1(
            family,
            1,
            tuple(entries),
            f"JOURNAL_INDEX:{frontier}",
            "SOURCE_TRANSACTIONAL_JOURNAL_V1",
        )

    def _verify_history_row(self, row: Mapping[str, object]) -> None:
        family = row["source_family"]
        if family not in _FAMILIES or row["operation"] not in {"BASELINE", "INSERT", "UPDATE"}:
            raise OnlySourceCutError("SOURCE_CUT_JOURNAL_CORRUPT")
        payload = row["source_row"]
        if not isinstance(payload, dict):
            raise OnlySourceCutError("SOURCE_CUT_JOURNAL_CORRUPT")
        decoded = dict(payload)
        for field in _DATETIME_FIELDS & decoded.keys():
            if decoded[field] is not None:
                decoded[field] = datetime.fromisoformat(str(decoded[field]))
        locator_field = (
            "attempt_id" if family == "RESEARCH_ATTEMPT" else ("run_id" if family == "RESEARCH_RUN" else "command_id")
        )
        if str(decoded.get(locator_field)) != row["native_locator"]:
            raise OnlySourceCutError("SOURCE_CUT_LOCATOR_CONFLICT")
        try:
            if family == "RESEARCH_RUN":
                # Pre-0031 journal payloads have no durable origin field. Keep
                # the current Run decoder strict and normalize only this
                # historical source representation from its existing Strategy
                # Composition reference.
                historical_run = dict(decoded)
                historical_run.setdefault(
                    "origin_kind",
                    "PRIVATE_STRATEGY"
                    if historical_run.get("strategy_research_composition_fingerprint") is not None
                    else "GENERAL",
                )
                run = OnlyPostgresResearchRunStore._decode(historical_run)
                if run.run_id.value != row["native_locator"]:
                    raise ValueError("Run identity mismatch")
            elif family == "RESEARCH_ATTEMPT":
                attempt = _decode_attempt(decoded)
                if attempt.attempt_id.value != row["native_locator"]:
                    raise ValueError("Attempt identity mismatch")
            else:
                # Product Command's exact domain constructors retain the source
                # schema and native command UUID; never infer from a copied index.
                self._verify_product_row(family, decoded)
        except Exception as exc:
            raise OnlySourceCutError("SOURCE_CUT_JOURNAL_CORRUPT") from exc

    @staticmethod
    def _verify_product_row(family: str, row: Mapping[str, object]) -> None:
        from onlyalpha.application.product_command_receipt import (
            OnlyProductCommandAdmissionV1,
            OnlyProductCommandId,
            OnlyProductCommandKind,
            OnlyProductCommandOutcomeKind,
            OnlyProductCommandOutcomeRef,
            OnlyProductCommandReceipt,
        )

        if family == "PRODUCT_COMMAND_ADMISSION":
            OnlyProductCommandAdmissionV1(
                OnlyProductCommandId(str(row["command_id"])),
                OnlyProductCommandKind(str(row["command_kind"])),
                str(row["command_fingerprint"]),
                int(cast(int, row["schema_version"])),
            )
        else:
            OnlyProductCommandReceipt(
                OnlyProductCommandId(str(row["command_id"])),
                OnlyProductCommandKind(str(row["command_kind"])),
                str(row["command_fingerprint"]),
                OnlyProductCommandOutcomeRef(
                    OnlyProductCommandOutcomeKind(str(row["outcome_kind"])), str(row["outcome_id"])
                ),
                cast(datetime, row["accepted_at"]),
                int(cast(int, row["schema_version"])),
            )

    @staticmethod
    def _require_family(family: str) -> None:
        if family not in _FAMILIES:
            raise OnlySourceCutError("SOURCE_CUT_FAMILY_INVALID")


class OnlyPostgresResearchFamilyCutReader:
    """Exact family-bound owner port for cross-source composition."""

    def __init__(self, owner: OnlyPostgresResearchSourceCutAuthority, family: str) -> None:
        self._owner = owner
        self._family = family

    def capture_closed_cut(self) -> OnlySourceClosedCutV1:
        return self._owner.capture_closed_cut(self._family)

    def load_closed_cut_verified(self, fingerprint: str) -> OnlySourceClosedCutV1:
        return self._owner.load_closed_cut_verified(fingerprint, self._family)

    def iter_closed_cut_observations_verified(self, fingerprint: str) -> tuple[OnlySourceObservationV1, ...]:
        return self._owner.iter_closed_cut_observations_verified(fingerprint, self._family)
