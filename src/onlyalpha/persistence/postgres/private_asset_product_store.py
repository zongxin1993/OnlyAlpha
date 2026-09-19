"""Disposable PostgreSQL Search Projection for DB-native Private Assets."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from onlyalpha.application.private_asset_product import (
    OnlyProductAssetSearchProjectionCorrupt,
    OnlyProductAssetSearchProjectionUnavailable,
    OnlyProductAssetSearchProjectionV1,
)

from .config import OnlyPostgresOperationalConnectionOptions


class OnlyPostgresPrivateAssetProductProjectionStore:
    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def publish(self, projection: OnlyProductAssetSearchProjectionV1, built_at: datetime) -> None:
        payload = projection.to_dict()
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                connection.execute(
                    "INSERT INTO private_asset_search_projection_revision ("
                    "projection_fingerprint, registry_fingerprint, completeness, payload, built_at, schema_version"
                    ") VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (projection_fingerprint) DO NOTHING",
                    (
                        projection.projection_fingerprint,
                        projection.registry_fingerprint,
                        projection.completeness.value,
                        Jsonb(payload),
                        built_at,
                        projection.schema_version,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM private_asset_search_projection_revision WHERE projection_fingerprint = %s",
                    (projection.projection_fingerprint,),
                ).fetchone()
                loaded, _ = self._from_row(row)
                if loaded != projection:
                    raise OnlyProductAssetSearchProjectionCorrupt("projection conflict")
                connection.execute(
                    "INSERT INTO private_asset_search_projection_active (singleton, projection_fingerprint) "
                    "VALUES (TRUE, %s) ON CONFLICT (singleton) DO UPDATE "
                    "SET projection_fingerprint = EXCLUDED.projection_fingerprint",
                    (projection.projection_fingerprint,),
                )
        except OnlyProductAssetSearchProjectionCorrupt:
            raise
        except psycopg.Error as exc:
            raise OnlyProductAssetSearchProjectionUnavailable("projection store unavailable") from exc

    def load_current(self) -> tuple[OnlyProductAssetSearchProjectionV1, datetime] | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT revision.* FROM private_asset_search_projection_active AS active "
                    "JOIN private_asset_search_projection_revision AS revision "
                    "USING (projection_fingerprint) WHERE active.singleton = TRUE"
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyProductAssetSearchProjectionUnavailable("projection store unavailable") from exc
        if row is None:
            return None
        return self._from_row(row)

    @staticmethod
    def _from_row(
        row: Mapping[str, object] | None,
    ) -> tuple[OnlyProductAssetSearchProjectionV1, datetime]:
        try:
            if row is None or not isinstance(row.get("payload"), Mapping):
                raise ValueError
            projection = OnlyProductAssetSearchProjectionV1.from_dict(cast(Mapping[str, object], row["payload"]))
            if (
                row.get("projection_fingerprint") != projection.projection_fingerprint
                or row.get("registry_fingerprint") != projection.registry_fingerprint
                or row.get("completeness") != projection.completeness.value
                or row.get("schema_version") != projection.schema_version
                or not isinstance(row.get("built_at"), datetime)
            ):
                raise ValueError
            return projection, cast(datetime, row["built_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyProductAssetSearchProjectionCorrupt("stored projection verification") from exc


__all__ = ["OnlyPostgresPrivateAssetProductProjectionStore"]
