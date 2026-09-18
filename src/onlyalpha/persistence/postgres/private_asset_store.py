"""PostgreSQL Private Alpha/Strategy authoring authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from onlyalpha.quant_assets.private import (
    OnlyPrivateAlphaAsset,
    OnlyPrivateAlphaDraft,
    OnlyPrivateAlphaRevision,
    OnlyPrivateAssetAuthorityUnavailableError,
    OnlyPrivateAssetConflictError,
    OnlyPrivateAssetCorruptError,
    OnlyPrivateAssetError,
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateAssetParentMismatchError,
    OnlyPrivateAssetPutDisposition,
    OnlyPrivateAssetStaleBaseError,
    OnlyPrivateStrategyAsset,
    OnlyPrivateStrategyDraft,
    OnlyPrivateStrategyRevision,
)

from .config import OnlyPostgresOperationalConnectionOptions

_Revision = TypeVar("_Revision", OnlyPrivateAlphaRevision, OnlyPrivateStrategyRevision)
_Draft = TypeVar("_Draft", OnlyPrivateAlphaDraft, OnlyPrivateStrategyDraft)


class OnlyPostgresPrivateAssetStore:
    """Sole durable authoring authority; stored source is never executed here."""

    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def put_alpha_asset(self, asset: OnlyPrivateAlphaAsset) -> OnlyPrivateAssetPutDisposition:
        return self._put_asset("private_alpha_asset", "alpha_id", asset.alpha_id, asset.schema_version)

    def load_alpha_asset(self, alpha_id: str) -> OnlyPrivateAlphaAsset:
        return OnlyPrivateAlphaAsset.from_dict(self._load_asset("private_alpha_asset", "alpha_id", alpha_id))

    def save_alpha_draft(self, draft: OnlyPrivateAlphaDraft) -> None:
        clean = OnlyPrivateAlphaDraft.from_dict(draft.to_dict())
        self._save_draft(
            "private_alpha_asset",
            "private_alpha_draft",
            "alpha_id",
            clean.alpha_id,
            clean.base_revision_fingerprint,
            clean.to_dict(),
            clean.schema_version,
        )

    def load_alpha_draft(self, alpha_id: str) -> OnlyPrivateAlphaDraft | None:
        payload = self._load_draft("private_alpha_draft", "alpha_id", alpha_id)
        return None if payload is None else OnlyPrivateAlphaDraft.from_dict(payload)

    def clear_alpha_draft(self, alpha_id: str) -> bool:
        return self._clear_draft("private_alpha_draft", "alpha_id", alpha_id)

    def publish_alpha_revision(self, alpha_id: str) -> tuple[OnlyPrivateAssetPutDisposition, OnlyPrivateAlphaRevision]:
        return self._publish(
            asset_table="private_alpha_asset",
            draft_table="private_alpha_draft",
            revision_table="private_alpha_revision",
            id_column="alpha_id",
            asset_id=alpha_id,
            draft_loader=OnlyPrivateAlphaDraft.from_dict,
            revision_builder=OnlyPrivateAlphaRevision.from_draft,
            revision_loader=OnlyPrivateAlphaRevision.from_dict,
            extra_columns=("source_text", "source_sha256"),
            extra_values=lambda revision: (revision.source_text, revision.source_sha256),
        )

    def load_alpha_revision(self, alpha_id: str, revision_fingerprint: str) -> OnlyPrivateAlphaRevision:
        return self._load_revision(
            "private_alpha_revision", "alpha_id", alpha_id, revision_fingerprint, OnlyPrivateAlphaRevision.from_dict
        )

    def list_alpha_revision_history(self, alpha_id: str) -> tuple[OnlyPrivateAlphaRevision, ...]:
        return self._history(
            "private_alpha_asset",
            "private_alpha_revision",
            "alpha_id",
            alpha_id,
            OnlyPrivateAlphaRevision.from_dict,
        )

    def put_strategy_asset(self, asset: OnlyPrivateStrategyAsset) -> OnlyPrivateAssetPutDisposition:
        return self._put_asset("private_strategy_asset", "strategy_id", asset.strategy_id, asset.schema_version)

    def load_strategy_asset(self, strategy_id: str) -> OnlyPrivateStrategyAsset:
        return OnlyPrivateStrategyAsset.from_dict(
            self._load_asset("private_strategy_asset", "strategy_id", strategy_id)
        )

    def save_strategy_draft(self, draft: OnlyPrivateStrategyDraft) -> None:
        clean = OnlyPrivateStrategyDraft.from_dict(draft.to_dict())
        self._save_draft(
            "private_strategy_asset",
            "private_strategy_draft",
            "strategy_id",
            clean.strategy_id,
            clean.base_revision_fingerprint,
            clean.to_dict(),
            clean.schema_version,
        )

    def load_strategy_draft(self, strategy_id: str) -> OnlyPrivateStrategyDraft | None:
        payload = self._load_draft("private_strategy_draft", "strategy_id", strategy_id)
        return None if payload is None else OnlyPrivateStrategyDraft.from_dict(payload)

    def clear_strategy_draft(self, strategy_id: str) -> bool:
        return self._clear_draft("private_strategy_draft", "strategy_id", strategy_id)

    def publish_strategy_revision(
        self, strategy_id: str
    ) -> tuple[OnlyPrivateAssetPutDisposition, OnlyPrivateStrategyRevision]:
        return self._publish(
            asset_table="private_strategy_asset",
            draft_table="private_strategy_draft",
            revision_table="private_strategy_revision",
            id_column="strategy_id",
            asset_id=strategy_id,
            draft_loader=OnlyPrivateStrategyDraft.from_dict,
            revision_builder=OnlyPrivateStrategyRevision.from_draft,
            revision_loader=OnlyPrivateStrategyRevision.from_dict,
            extra_columns=("definition_fingerprint",),
            extra_values=lambda revision: (revision.definition_fingerprint,),
        )

    def load_strategy_revision(self, strategy_id: str, revision_fingerprint: str) -> OnlyPrivateStrategyRevision:
        return self._load_revision(
            "private_strategy_revision",
            "strategy_id",
            strategy_id,
            revision_fingerprint,
            OnlyPrivateStrategyRevision.from_dict,
        )

    def list_strategy_revision_history(self, strategy_id: str) -> tuple[OnlyPrivateStrategyRevision, ...]:
        return self._history(
            "private_strategy_asset",
            "private_strategy_revision",
            "strategy_id",
            strategy_id,
            OnlyPrivateStrategyRevision.from_dict,
        )

    def _put_asset(
        self, table: str, id_column: str, asset_id: str, schema_version: int
    ) -> OnlyPrivateAssetPutDisposition:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                inserted = connection.execute(
                    f"INSERT INTO {table} ({id_column}, schema_version) VALUES (%s, %s) "
                    f"ON CONFLICT ({id_column}) DO NOTHING RETURNING {id_column}",
                    (asset_id, schema_version),
                ).fetchone()
                row = connection.execute(
                    f"SELECT {id_column}, schema_version FROM {table} WHERE {id_column} = %s", (asset_id,)
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyPrivateAssetAuthorityUnavailableError(asset_id) from exc
        if row != {id_column: asset_id, "schema_version": schema_version}:
            raise OnlyPrivateAssetConflictError(asset_id)
        return OnlyPrivateAssetPutDisposition.CREATED if inserted is not None else OnlyPrivateAssetPutDisposition.REUSED

    def _load_asset(self, table: str, id_column: str, asset_id: str) -> Mapping[str, object]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    f"SELECT {id_column}, schema_version FROM {table} WHERE {id_column} = %s", (asset_id,)
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyPrivateAssetAuthorityUnavailableError(asset_id) from exc
        if row is None:
            raise OnlyPrivateAssetNotFoundError(asset_id)
        return row

    def _save_draft(
        self,
        asset_table: str,
        draft_table: str,
        id_column: str,
        asset_id: str,
        base_revision_fingerprint: str | None,
        payload: dict[str, object],
        schema_version: int,
    ) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                exists = connection.execute(
                    f"SELECT 1 FROM {asset_table} WHERE {id_column} = %s", (asset_id,)
                ).fetchone()
                if exists is None:
                    raise OnlyPrivateAssetNotFoundError(asset_id)
                connection.execute(
                    f"INSERT INTO {draft_table} ({id_column}, base_revision_fingerprint, payload, schema_version) "
                    "VALUES (%s, %s, %s, %s) "
                    f"ON CONFLICT ({id_column}) DO UPDATE SET "
                    "base_revision_fingerprint = EXCLUDED.base_revision_fingerprint, "
                    "payload = EXCLUDED.payload, schema_version = EXCLUDED.schema_version",
                    (asset_id, base_revision_fingerprint, Jsonb(payload), schema_version),
                )
        except OnlyPrivateAssetNotFoundError:
            raise
        except psycopg.IntegrityError as exc:
            raise OnlyPrivateAssetParentMismatchError(asset_id) from exc
        except psycopg.Error as exc:
            raise OnlyPrivateAssetAuthorityUnavailableError(asset_id) from exc

    def _load_draft(self, table: str, id_column: str, asset_id: str) -> Mapping[str, object] | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(f"SELECT * FROM {table} WHERE {id_column} = %s", (asset_id,)).fetchone()
        except psycopg.Error as exc:
            raise OnlyPrivateAssetAuthorityUnavailableError(asset_id) from exc
        if row is None:
            return None
        payload = row["payload"]
        if (
            not isinstance(payload, Mapping)
            or payload.get(id_column) != asset_id
            or payload.get("base_revision_fingerprint") != row["base_revision_fingerprint"]
            or payload.get("schema_version") != row["schema_version"]
        ):
            raise OnlyPrivateAssetCorruptError(asset_id)
        return cast(Mapping[str, object], payload)

    def _clear_draft(self, table: str, id_column: str, asset_id: str) -> bool:
        try:
            with psycopg.connect(self._dsn) as connection:
                deleted = connection.execute(
                    f"DELETE FROM {table} WHERE {id_column} = %s RETURNING {id_column}", (asset_id,)
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyPrivateAssetAuthorityUnavailableError(asset_id) from exc
        return deleted is not None

    def _publish(
        self,
        *,
        asset_table: str,
        draft_table: str,
        revision_table: str,
        id_column: str,
        asset_id: str,
        draft_loader: Callable[[Mapping[str, object]], _Draft],
        revision_builder: Callable[[_Draft], _Revision],
        revision_loader: Callable[[Mapping[str, object]], _Revision],
        extra_columns: tuple[str, ...],
        extra_values: Callable[[_Revision], tuple[object, ...]],
    ) -> tuple[OnlyPrivateAssetPutDisposition, _Revision]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                asset = connection.execute(
                    f"SELECT current_revision_fingerprint FROM {asset_table} WHERE {id_column} = %s FOR UPDATE",
                    (asset_id,),
                ).fetchone()
                if asset is None:
                    raise OnlyPrivateAssetNotFoundError(asset_id)
                draft_row = connection.execute(
                    f"SELECT * FROM {draft_table} WHERE {id_column} = %s", (asset_id,)
                ).fetchone()
                if draft_row is None:
                    raise OnlyPrivateAssetNotFoundError(f"draft:{asset_id}")
                raw_draft = draft_row["payload"]
                if (
                    not isinstance(raw_draft, Mapping)
                    or raw_draft.get(id_column) != asset_id
                    or raw_draft.get("base_revision_fingerprint") != draft_row["base_revision_fingerprint"]
                    or raw_draft.get("schema_version") != draft_row["schema_version"]
                ):
                    raise OnlyPrivateAssetCorruptError(f"draft:{asset_id}")
                draft = draft_loader(cast(Mapping[str, object], raw_draft))
                revision: _Revision = revision_builder(draft)
                current = asset["current_revision_fingerprint"]
                if revision.revision_fingerprint == current:
                    actual = self._load_revision_in_transaction(
                        connection, revision_table, id_column, asset_id, revision.revision_fingerprint, revision_loader
                    )
                    if actual != revision:
                        raise OnlyPrivateAssetConflictError(revision.revision_fingerprint)
                    return OnlyPrivateAssetPutDisposition.REUSED, actual
                if revision.parent_revision_fingerprint != current:
                    raise OnlyPrivateAssetStaleBaseError(asset_id)
                if current is not None:
                    parent = self._load_revision_in_transaction(
                        connection, revision_table, id_column, asset_id, str(current), revision_loader
                    )
                    if parent.revision_fingerprint != revision.parent_revision_fingerprint:
                        raise OnlyPrivateAssetParentMismatchError(asset_id)
                columns = (
                    "revision_fingerprint",
                    id_column,
                    "parent_revision_fingerprint",
                    *extra_columns,
                    "payload",
                    "schema_version",
                )
                additional_values: tuple[object, ...] = extra_values(revision)
                values = (
                    revision.revision_fingerprint,
                    asset_id,
                    revision.parent_revision_fingerprint,
                    *additional_values,
                    Jsonb(revision.to_dict()),
                    revision.schema_version,
                )
                placeholders = ", ".join("%s" for _ in values)
                inserted = connection.execute(
                    f"INSERT INTO {revision_table} ({', '.join(columns)}) VALUES ({placeholders}) "
                    "ON CONFLICT (revision_fingerprint) DO NOTHING RETURNING revision_fingerprint",
                    values,
                ).fetchone()
                actual = self._load_revision_in_transaction(
                    connection, revision_table, id_column, asset_id, revision.revision_fingerprint, revision_loader
                )
                if actual != revision:
                    raise OnlyPrivateAssetConflictError(revision.revision_fingerprint)
                updated = connection.execute(
                    f"UPDATE {asset_table} SET current_revision_fingerprint = %s WHERE {id_column} = %s "
                    "AND current_revision_fingerprint IS NOT DISTINCT FROM %s RETURNING current_revision_fingerprint",
                    (revision.revision_fingerprint, asset_id, revision.parent_revision_fingerprint),
                ).fetchone()
                if updated is None:
                    raise OnlyPrivateAssetStaleBaseError(asset_id)
                disposition = (
                    OnlyPrivateAssetPutDisposition.CREATED
                    if inserted is not None
                    else OnlyPrivateAssetPutDisposition.REUSED
                )
                return disposition, actual
        except (
            OnlyPrivateAssetConflictError,
            OnlyPrivateAssetCorruptError,
            OnlyPrivateAssetNotFoundError,
            OnlyPrivateAssetParentMismatchError,
            OnlyPrivateAssetStaleBaseError,
        ):
            raise
        except psycopg.IntegrityError as exc:
            raise OnlyPrivateAssetParentMismatchError(asset_id) from exc
        except psycopg.Error as exc:
            raise OnlyPrivateAssetAuthorityUnavailableError(asset_id) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyPrivateAssetCorruptError(asset_id) from exc

    def _load_revision(
        self,
        table: str,
        id_column: str,
        asset_id: str,
        revision_fingerprint: str,
        loader: Callable[[Mapping[str, object]], _Revision],
    ) -> _Revision:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                return self._load_revision_in_transaction(
                    connection, table, id_column, asset_id, revision_fingerprint, loader
                )
        except (OnlyPrivateAssetCorruptError, OnlyPrivateAssetNotFoundError):
            raise
        except psycopg.Error as exc:
            raise OnlyPrivateAssetAuthorityUnavailableError(asset_id) from exc

    @staticmethod
    def _load_revision_in_transaction(
        connection: psycopg.Connection[object],
        table: str,
        id_column: str,
        asset_id: str,
        revision_fingerprint: str,
        loader: Callable[[Mapping[str, object]], _Revision],
    ) -> _Revision:
        row = connection.execute(
            f"SELECT * FROM {table} WHERE {id_column} = %s AND revision_fingerprint = %s",
            (asset_id, revision_fingerprint),
        ).fetchone()
        if row is None:
            raise OnlyPrivateAssetNotFoundError(revision_fingerprint)
        if not isinstance(row, Mapping):
            raise OnlyPrivateAssetCorruptError(revision_fingerprint)
        return OnlyPostgresPrivateAssetStore._revision_from_row(row, id_column, asset_id, revision_fingerprint, loader)

    @staticmethod
    def _revision_from_row(
        row: Mapping[str, object],
        id_column: str,
        asset_id: str,
        revision_fingerprint: str,
        loader: Callable[[Mapping[str, object]], _Revision],
    ) -> _Revision:
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            raise OnlyPrivateAssetCorruptError(revision_fingerprint)
        try:
            result = loader(cast(Mapping[str, object], payload))
        except OnlyPrivateAssetCorruptError:
            raise
        except (OnlyPrivateAssetError, KeyError, TypeError, ValueError) as exc:
            raise OnlyPrivateAssetCorruptError(revision_fingerprint) from exc
        if (
            result.revision_fingerprint != revision_fingerprint
            or row.get("revision_fingerprint") != revision_fingerprint
            or row.get(id_column) != asset_id
            or row.get("parent_revision_fingerprint") != result.parent_revision_fingerprint
            or row.get("schema_version") != result.schema_version
        ):
            raise OnlyPrivateAssetCorruptError(revision_fingerprint)
        if isinstance(result, OnlyPrivateAlphaRevision) and (
            row.get("source_text") != result.source_text or row.get("source_sha256") != result.source_sha256
        ):
            raise OnlyPrivateAssetCorruptError(revision_fingerprint)
        if (
            isinstance(result, OnlyPrivateStrategyRevision)
            and row.get("definition_fingerprint") != result.definition_fingerprint
        ):
            raise OnlyPrivateAssetCorruptError(revision_fingerprint)
        return result

    def _history(
        self,
        asset_table: str,
        revision_table: str,
        id_column: str,
        asset_id: str,
        loader: Callable[[Mapping[str, object]], _Revision],
    ) -> tuple[_Revision, ...]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                asset = connection.execute(
                    f"SELECT current_revision_fingerprint FROM {asset_table} WHERE {id_column} = %s", (asset_id,)
                ).fetchone()
                if asset is None:
                    raise OnlyPrivateAssetNotFoundError(asset_id)
                rows = connection.execute(
                    f"SELECT * FROM {revision_table} WHERE {id_column} = %s",
                    (asset_id,),
                ).fetchall()
        except OnlyPrivateAssetNotFoundError:
            raise
        except psycopg.Error as exc:
            raise OnlyPrivateAssetAuthorityUnavailableError(asset_id) from exc
        try:
            revisions = {
                str(row["revision_fingerprint"]): self._revision_from_row(
                    row,
                    id_column,
                    asset_id,
                    str(row["revision_fingerprint"]),
                    loader,
                )
                for row in rows
            }
            current = asset["current_revision_fingerprint"]
            ordered: list[_Revision] = []
            while current is not None:
                revision = revisions.pop(str(current))
                ordered.append(revision)
                current = revision.parent_revision_fingerprint
            if revisions:
                raise ValueError("disconnected revision history")
            return tuple(reversed(ordered))
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyPrivateAssetCorruptError(asset_id) from exc


__all__ = ["OnlyPostgresPrivateAssetStore"]
