"""Append-only PostgreSQL authority for Strategy Research Composition facts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from onlyalpha.canonical import only_canonical_json
from onlyalpha.quant_assets.private_strategy import (
    OnlyPrivateStrategyFactorRevisionDependencyV1,
    OnlyPrivateStrategyResearchContextV1,
)
from onlyalpha.quant_assets.private_strategy_composition import (
    OnlyPrivateStrategyResearchCompositionError,
    OnlyPrivateStrategyResearchCompositionV1,
)

from .config import OnlyPostgresOperationalConnectionOptions


class OnlyPostgresPrivateStrategyResearchCompositionStore:
    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def put(
        self,
        composition: OnlyPrivateStrategyResearchCompositionV1,
        context: OnlyPrivateStrategyResearchContextV1,
    ) -> None:
        clean = OnlyPrivateStrategyResearchCompositionV1.from_dict(composition.to_dict())
        context = OnlyPrivateStrategyResearchContextV1.from_dict(context.to_dict())
        if context.research_context_fingerprint != clean.research_context_fingerprint:
            raise OnlyPrivateStrategyResearchCompositionError(
                "PRIVATE_STRATEGY_COMPOSITION_MISMATCH", "Research Context fingerprint differs"
            )
        values = (
            clean.composition_fingerprint,
            clean.schema_version,
            clean.private_strategy_id,
            clean.private_strategy_revision_fingerprint,
            clean.private_strategy_definition_fingerprint,
            clean.research_context_fingerprint,
            Jsonb([item.to_dict() for item in clean.factor_revision_bindings]),
            clean.catalog_generation_fingerprint,
            clean.research_definition_fingerprint,
            Jsonb(context.to_dict()),
        )
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                connection.execute(
                    "INSERT INTO private_strategy_research_composition ("
                    "composition_fingerprint, schema_version, private_strategy_id, "
                    "private_strategy_revision_fingerprint, private_strategy_definition_fingerprint, "
                    "research_context_fingerprint, factor_revision_bindings, catalog_generation_fingerprint, "
                    "research_definition_fingerprint, research_context_payload"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (composition_fingerprint) DO NOTHING",
                    values,
                )
                row = connection.execute(
                    "SELECT * FROM private_strategy_research_composition WHERE composition_fingerprint = %s",
                    (clean.composition_fingerprint,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyPrivateStrategyResearchCompositionError(
                "PRIVATE_STRATEGY_COMPOSITION_AUTHORITY_UNAVAILABLE", str(exc)
            ) from exc
        if row is None or self._decode(cast(Mapping[str, object], row)) != clean:
            raise OnlyPrivateStrategyResearchCompositionError("PRIVATE_STRATEGY_COMPOSITION_MISMATCH")

    def load(self, composition_fingerprint: str) -> OnlyPrivateStrategyResearchCompositionV1:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM private_strategy_research_composition WHERE composition_fingerprint = %s",
                    (composition_fingerprint,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyPrivateStrategyResearchCompositionError(
                "PRIVATE_STRATEGY_COMPOSITION_AUTHORITY_UNAVAILABLE", str(exc)
            ) from exc
        if row is None:
            raise OnlyPrivateStrategyResearchCompositionError(
                "PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE", composition_fingerprint
            )
        return self._decode(cast(Mapping[str, object], row))

    def load_context(self, composition_fingerprint: str) -> OnlyPrivateStrategyResearchContextV1:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT research_context_payload, research_context_fingerprint "
                    "FROM private_strategy_research_composition WHERE composition_fingerprint = %s",
                    (composition_fingerprint,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyPrivateStrategyResearchCompositionError(
                "PRIVATE_STRATEGY_COMPOSITION_AUTHORITY_UNAVAILABLE", str(exc)
            ) from exc
        if row is None:
            raise OnlyPrivateStrategyResearchCompositionError(
                "PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE", composition_fingerprint
            )
        try:
            context = OnlyPrivateStrategyResearchContextV1.from_dict(
                cast(Mapping[str, object], row["research_context_payload"])
            )
            if context.research_context_fingerprint != row["research_context_fingerprint"]:
                raise ValueError("Research Context fingerprint mismatch")
            if only_canonical_json(context.to_dict()) != only_canonical_json(row["research_context_payload"]):
                raise ValueError("Research Context payload is not canonical")
            return context
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyPrivateStrategyResearchCompositionError(
                "PRIVATE_STRATEGY_COMPOSITION_CORRUPT", composition_fingerprint
            ) from exc

    def _decode(self, row: Mapping[str, object]) -> OnlyPrivateStrategyResearchCompositionV1:
        try:
            raw_bindings = row["factor_revision_bindings"]
            if not isinstance(raw_bindings, list):
                raise ValueError("factor bindings are not an array")
            canonical_bindings = [
                OnlyPrivateStrategyFactorRevisionDependencyV1.from_dict(cast(Mapping[str, object], item)).to_dict()
                for item in raw_bindings
                if isinstance(item, Mapping)
            ]
            if len(canonical_bindings) != len(raw_bindings) or only_canonical_json(raw_bindings) != only_canonical_json(
                canonical_bindings
            ):
                raise ValueError("factor bindings are not canonical")
            payload = {
                "schema_version": row["schema_version"],
                "private_strategy_id": row["private_strategy_id"],
                "private_strategy_revision_fingerprint": row["private_strategy_revision_fingerprint"],
                "private_strategy_definition_fingerprint": row["private_strategy_definition_fingerprint"],
                "research_context_fingerprint": row["research_context_fingerprint"],
                "factor_revision_bindings": raw_bindings,
                "catalog_generation_fingerprint": row["catalog_generation_fingerprint"],
                "research_definition_fingerprint": row["research_definition_fingerprint"],
                "composition_fingerprint": row["composition_fingerprint"],
            }
            composition = OnlyPrivateStrategyResearchCompositionV1.from_dict(payload)
            context = OnlyPrivateStrategyResearchContextV1.from_dict(
                cast(Mapping[str, object], row["research_context_payload"])
            )
            if context.research_context_fingerprint != composition.research_context_fingerprint:
                raise ValueError("Research Context fingerprint mismatch")
            if only_canonical_json(context.to_dict()) != only_canonical_json(row["research_context_payload"]):
                raise ValueError("Research Context payload is not canonical")
            return composition
        except (KeyError, TypeError, ValueError, OnlyPrivateStrategyResearchCompositionError) as exc:
            raise OnlyPrivateStrategyResearchCompositionError(
                "PRIVATE_STRATEGY_COMPOSITION_CORRUPT", str(row.get("composition_fingerprint", "unknown"))
            ) from exc


__all__ = ["OnlyPostgresPrivateStrategyResearchCompositionStore"]
