"""PostgreSQL authority for the one Research deployment semantic-store binding."""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from onlyalpha.research.operations.deployment import (
    OnlyResearchDeploymentError,
    OnlyResearchDeploymentErrorCode,
    OnlyResearchSemanticStoreId,
)
from onlyalpha.research.run.errors import OnlyResearchRunStoreUnavailableError

from .config import OnlyPostgresOperationalConnectionOptions


class OnlyPostgresResearchDeploymentStore:
    def __init__(
        self,
        dsn: str,
        options: OnlyPostgresOperationalConnectionOptions | None = None,
    ) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def load_semantic_store_id(self) -> OnlyResearchSemanticStoreId:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT semantic_store_id FROM research_deployment_semantic_store_binding WHERE singleton = TRUE"
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research deployment binding unavailable") from exc
        if row is None:
            raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.DEPLOYMENT_BINDING_MISSING)
        try:
            return OnlyResearchSemanticStoreId(str(row["semantic_store_id"]))
        except ValueError as exc:
            raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_CORRUPT) from exc

    def initialize(self, store_id: OnlyResearchSemanticStoreId) -> OnlyResearchSemanticStoreId:
        """Explicit operator-only idempotent bind. No update/rebind surface exists."""

        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute(
                    "INSERT INTO research_deployment_semantic_store_binding (singleton, semantic_store_id) "
                    "VALUES (TRUE, %s) ON CONFLICT (singleton) DO NOTHING",
                    (str(store_id),),
                )
                row = connection.execute(
                    "SELECT semantic_store_id FROM research_deployment_semantic_store_binding WHERE singleton = TRUE"
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError(
                "Research deployment binding initialization unavailable"
            ) from exc
        if row is None:
            raise OnlyResearchRunStoreUnavailableError("Research deployment binding initialization was not observable")
        actual = OnlyResearchSemanticStoreId(str(row[0]))
        if actual != store_id:
            raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH)
        return actual


__all__ = ["OnlyPostgresResearchDeploymentStore"]
