from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import pytest

from onlyalpha.application.private_asset_product import (
    OnlyPrivateAssetProductService,
    OnlyProductAssetSearchProjectionCorrupt,
    OnlyProductAssetSearchProjectionService,
    OnlyProductAssetSearchQueryV1,
    OnlyProductAssetSearchStatus,
)
from onlyalpha.persistence.postgres import (
    OnlyPostgresPrivateAssetProductProjectionStore,
    OnlyPostgresPrivateAssetStore,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.quant_assets import OnlyPrivateFactorAsset, OnlyPrivateStrategyAsset
from tests.research.postgres.test_private_asset_authority import _factor, _strategy

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]

NOW = datetime(2026, 9, 19, tzinfo=UTC)


def _published_assets(postgres_dsn: str) -> OnlyPostgresPrivateAssetStore:
    assets = OnlyPostgresPrivateAssetStore(postgres_dsn)
    assets.put_factor_asset(OnlyPrivateFactorAsset("private.factor.momentum"))
    assets.save_factor_draft(_factor())
    assets.publish_factor_revision("private.factor.momentum")
    assets.put_strategy_asset(OnlyPrivateStrategyAsset("private.strategy.momentum"))
    assets.save_strategy_draft(_strategy())
    assets.publish_strategy_revision("private.strategy.momentum")
    assets.put_factor_asset(OnlyPrivateFactorAsset("private.factor.draft_only"))
    assets.save_factor_draft(_factor("private.factor.draft_only"))
    return assets


def test_current_registry_enumeration_excludes_drafts_and_is_sorted(postgres_dsn: str) -> None:
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate()[-1] == ("0037_market_data_acquisition_attempt")
    assets = _published_assets(postgres_dsn)

    factors = assets.list_current_factor_revisions()
    strategies = assets.list_current_strategy_revisions()

    assert [item.factor_id for item in factors] == ["private.factor.momentum"]
    assert [item.strategy_id for item in strategies] == ["private.strategy.momentum"]


def test_search_projection_delete_rebuild_preserves_authority_and_logical_results(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    assets = _published_assets(postgres_dsn)
    product = OnlyPrivateAssetProductService(assets)
    store = OnlyPostgresPrivateAssetProductProjectionStore(postgres_dsn)
    search = OnlyProductAssetSearchProjectionService(product, store, lambda: NOW)
    first = search.rebuild()
    before = search.search(OnlyProductAssetSearchQueryV1(text="momentum"))

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DELETE FROM private_asset_search_projection_revision")

    assert (
        search.search(OnlyProductAssetSearchQueryV1(text="momentum")).status
        is OnlyProductAssetSearchStatus.PROJECTION_UNAVAILABLE
    )
    assert (
        assets.load_factor_revision(
            first.entries[0].locator.private_asset_id, first.entries[0].locator.revision_fingerprint
        ).source_sha256
        == first.entries[0].locator.content_fingerprint
    )

    second = search.rebuild()
    after = search.search(OnlyProductAssetSearchQueryV1(text="momentum"))
    assert second == first
    assert after.results == before.results
    assert after.status is OnlyProductAssetSearchStatus.MATCH


def test_search_projection_corruption_is_detected_and_never_becomes_no_match(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    assets = _published_assets(postgres_dsn)
    store = OnlyPostgresPrivateAssetProductProjectionStore(postgres_dsn)
    search = OnlyProductAssetSearchProjectionService(OnlyPrivateAssetProductService(assets), store, lambda: NOW)
    built = search.rebuild()

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "ALTER TABLE private_asset_search_projection_revision DISABLE TRIGGER "
            "private_asset_search_projection_revision_immutable_trigger"
        )
        connection.execute(
            "UPDATE private_asset_search_projection_revision SET payload = '{}'::jsonb "
            "WHERE projection_fingerprint = %s",
            (built.projection_fingerprint,),
        )
        connection.execute(
            "ALTER TABLE private_asset_search_projection_revision ENABLE TRIGGER "
            "private_asset_search_projection_revision_immutable_trigger"
        )

    with pytest.raises(OnlyProductAssetSearchProjectionCorrupt, match="PRIVATE_ASSET_SEARCH_PROJECTION_CORRUPT"):
        search.search(OnlyProductAssetSearchQueryV1(text="missing"))


def test_search_projection_staleness_is_visible_after_new_current_revision(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    assets = _published_assets(postgres_dsn)
    search = OnlyProductAssetSearchProjectionService(
        OnlyPrivateAssetProductService(assets),
        OnlyPostgresPrivateAssetProductProjectionStore(postgres_dsn),
        lambda: NOW,
    )
    search.rebuild()
    old = assets.list_current_factor_revisions()[0]
    assets.save_factor_draft(_factor(base_revision_fingerprint=old.revision_fingerprint, description="Changed"))
    assets.publish_factor_revision(old.factor_id)

    outcome = search.search(OnlyProductAssetSearchQueryV1(text="absent"))

    assert outcome.status is OnlyProductAssetSearchStatus.PROJECTION_INCOMPLETE
    assert outcome.projection_stale is True
