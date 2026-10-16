"""Atomic owner configuration revisions using the global Product Command authority."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from onlyalpha.application.market_data_product import OnlyMarketDataProductError, OnlyMarketDataSourceReferenceV1
from onlyalpha.application.product_command_authority import OnlyProductCommandConflictError
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.application.watchlists import OnlyWatchlist, OnlyWatchlistBook, OnlyWatchlistError, OnlyWatchlistMember
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.core.clock import only_system_utc_now
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreId

from .config import OnlyPostgresOperationalConnectionOptions
from .product_command_authority import OnlyPostgresProductCommandAuthority as Commands


class OnlyPostgresWatchlistStore:
    def __init__(self, dsn: str, namespace: OnlyResearchSemanticStoreId) -> None:
        self._dsn = OnlyPostgresOperationalConnectionOptions().apply(dsn)
        self._namespace = namespace.value

    def _read_revision(self, row: Any) -> OnlyWatchlistBook:
        try:
            payload, representation = row[2], row[3]
            if type(representation) is not int or representation not in (1, 2):
                raise ValueError
            if set(payload) != {"version", "lists"} or not isinstance(payload["lists"], list):
                raise ValueError
            lists = []
            for item in payload["lists"]:
                if representation == 1:
                    # Immutable 0051 facts retain their original bytes and identities.
                    if set(item) != {"list_id", "name", "source", "instrument_ids"}:
                        raise ValueError
                    source = OnlyMarketDataSourceReferenceV1(**item["source"])
                    if source.expected_type_id is None:
                        raise ValueError
                    if not isinstance(item["instrument_ids"], list):
                        raise ValueError
                    members = tuple(OnlyWatchlistMember(source, value) for value in item["instrument_ids"])
                else:
                    if set(item) != {"list_id", "name", "members"} or not isinstance(item["members"], list):
                        raise ValueError
                    members_list = []
                    for member in item["members"]:
                        if set(member) != {"source", "instrument_id"}:
                            raise ValueError
                        members_list.append(
                            OnlyWatchlistMember(
                                OnlyMarketDataSourceReferenceV1(**member["source"]), member["instrument_id"]
                            )
                        )
                    members = tuple(members_list)
                lists.append(OnlyWatchlist(item["list_id"], item["name"], members))
            book = OnlyWatchlistBook(payload["version"], tuple(lists))
            if book.version != row[0] or row[1] != self._fingerprint(payload):
                raise ValueError
            return book
        except (KeyError, TypeError, ValueError, AttributeError, OnlyMarketDataProductError) as error:
            raise OnlyWatchlistError("WATCHLIST_HISTORY_CORRUPT") from error

    def _fingerprint(self, payload: Any) -> str:
        return only_canonical_fingerprint({"namespace_id": self._namespace, "book": payload})

    def _intent_fingerprint(self, expected_version: int, lists: Any) -> str:
        return only_canonical_fingerprint(
            {"namespace_id": self._namespace, "expected_version": expected_version, "lists": lists}
        )

    def _historical_intent(self, expected_version: int, lists: tuple[OnlyWatchlist, ...]) -> str | None:
        # Necessary for exact replay of immutable admissions written before migration 0052.
        # Empty old lists cannot be reconstructed from v2 intent alone (their Source is absent).
        original = []
        for item in lists:
            if not item.members or any(member.source != item.members[0].source for member in item.members):
                return None
            original.append(
                {
                    "list_id": item.list_id,
                    "name": item.name,
                    "source": asdict(item.members[0].source),
                    "instrument_ids": [member.instrument_id for member in item.members],
                }
            )
        return self._intent_fingerprint(expected_version, original)

    def _current(self, connection: psycopg.Connection[Any]) -> OnlyWatchlistBook:
        row = connection.execute(
            """SELECT r.version, r.fingerprint, r.book_json, r.representation_version, r.command_id::text,
                (SELECT max(version) FROM watchlist_revision WHERE namespace_id = h.namespace_id),
                (SELECT count(*) FROM watchlist_revision WHERE namespace_id = h.namespace_id)
                FROM watchlist_head h JOIN watchlist_revision r USING(namespace_id, version)
                WHERE h.namespace_id = %s""",
            (self._namespace,),
        ).fetchone()
        if row is None:
            if connection.execute(
                "SELECT 1 FROM watchlist_revision WHERE namespace_id = %s LIMIT 1", (self._namespace,)
            ).fetchone():
                raise OnlyWatchlistError("WATCHLIST_HISTORY_CORRUPT")
            return OnlyWatchlistBook(0, ())
        if row[0] != row[5] or row[0] != row[6]:
            raise OnlyWatchlistError("WATCHLIST_HISTORY_CORRUPT")
        decoded = self._read_revision(row)
        verified = self._command(connection, OnlyProductCommandId(row[4]))
        if verified != decoded:
            raise OnlyWatchlistError("WATCHLIST_HISTORY_CORRUPT")
        return decoded

    def read(self) -> OnlyWatchlistBook:
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                return self._current(connection)
        except psycopg.Error as error:
            raise OnlyWatchlistError("WATCHLIST_UNAVAILABLE") from error

    def _command(self, connection: psycopg.Connection[Any], command: OnlyProductCommandId) -> OnlyWatchlistBook | None:
        receipt = Commands.load_verified_receipt_in_transaction(connection, command)
        admission = Commands.load_admission_in_transaction(connection, command)
        if receipt is None:
            if admission is not None:
                if admission.command_kind is not OnlyProductCommandKind.SAVE_WATCHLISTS:
                    raise OnlyWatchlistError("WATCHLIST_COMMAND_CONFLICT")
                raise OnlyWatchlistError("WATCHLIST_COMMAND_UNKNOWN")
            return None
        if (
            receipt.command_kind is not OnlyProductCommandKind.SAVE_WATCHLISTS
            or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.WATCHLIST_REVISION
        ):
            raise OnlyWatchlistError("WATCHLIST_COMMAND_CONFLICT")
        row = connection.execute(
            """SELECT version, fingerprint, book_json, representation_version FROM watchlist_revision
            WHERE namespace_id = %s AND fingerprint = %s AND command_id = %s""",
            (self._namespace, receipt.outcome_ref.outcome_id, command.value),
        ).fetchone()
        if row is None:
            raise OnlyWatchlistError("WATCHLIST_HISTORY_CORRUPT")
        book = self._read_revision(row)
        expected = self._intent_fingerprint(book.version - 1, row[2]["lists"])
        if receipt.command_fingerprint != expected:
            raise OnlyWatchlistError("WATCHLIST_HISTORY_CORRUPT")
        return book

    def command(self, command_id: str) -> OnlyWatchlistBook | None:
        try:
            with psycopg.connect(self._dsn) as connection:
                command = OnlyProductCommandId(command_id)
                Commands.lock_command(connection, command)
                return self._command(connection, command)
        except psycopg.Error as error:
            raise OnlyWatchlistError("WATCHLIST_UNAVAILABLE") from error

    def save(self, command_id: str, expected_version: int, lists: tuple[OnlyWatchlist, ...]) -> OnlyWatchlistBook:
        OnlyWatchlistBook(expected_version, lists)
        book = OnlyWatchlistBook(expected_version + 1, lists)
        admission = OnlyProductCommandAdmissionV1(
            OnlyProductCommandId(command_id),
            OnlyProductCommandKind.SAVE_WATCHLISTS,
            only_canonical_fingerprint(
                {"namespace_id": self._namespace, "expected_version": expected_version, "lists": lists}
            ),
        )
        try:
            with psycopg.connect(self._dsn) as connection:
                Commands.lock_command(connection, admission.command_id)
                bound = Commands.load_admission_in_transaction(connection, admission.command_id)
                if bound is not None:
                    if bound.command_kind is not admission.command_kind:
                        raise OnlyWatchlistError("WATCHLIST_COMMAND_CONFLICT")
                    try:
                        existing = self._command(connection, admission.command_id)
                    except OnlyWatchlistError as error:
                        if error.code != "WATCHLIST_COMMAND_UNKNOWN":
                            raise
                        if bound.command_fingerprint not in {
                            admission.command_fingerprint,
                            self._historical_intent(expected_version, lists),
                        }:
                            raise OnlyWatchlistError("WATCHLIST_COMMAND_CONFLICT") from error
                        raise
                    if existing is None or existing.version != expected_version + 1 or existing.lists != lists:
                        raise OnlyWatchlistError("WATCHLIST_COMMAND_CONFLICT")
                    return existing
                Commands.insert_or_verify_admission(connection, admission)
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("watchlists:" + self._namespace,)
                )
                if self._current(connection).version != expected_version:
                    raise OnlyWatchlistError("WATCHLIST_VERSION_CONFLICT")
                fingerprint = self._fingerprint(asdict(book))
                connection.execute(
                    """INSERT INTO watchlist_revision(namespace_id, version, fingerprint, book_json, command_id, representation_version)
                    VALUES (%s,%s,%s,%s,%s,2)""",
                    (self._namespace, book.version, fingerprint, Jsonb(asdict(book)), command_id),
                )
                connection.execute(
                    """INSERT INTO watchlist_head(namespace_id, version) VALUES (%s,%s)
                    ON CONFLICT(namespace_id) DO UPDATE SET version = EXCLUDED.version""",
                    (self._namespace, book.version),
                )
                Commands.insert_verified_receipt(
                    connection,
                    OnlyProductCommandReceipt(
                        admission.command_id,
                        admission.command_kind,
                        admission.command_fingerprint,
                        OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.WATCHLIST_REVISION, fingerprint),
                        only_system_utc_now(),
                    ),
                )
                return book
        except OnlyProductCommandConflictError as error:
            raise OnlyWatchlistError("WATCHLIST_COMMAND_CONFLICT") from error
        except psycopg.Error as error:
            raise OnlyWatchlistError("WATCHLIST_UNAVAILABLE") from error
