from __future__ import annotations

import pytest

from onlyalpha.persistence.postgres import OnlyPostgresPrivateAssetStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.quant_assets import OnlyPrivateFactorAsset, OnlyPrivateStrategyAsset
from tests.research.postgres.migration_support import current_migrations
from tests.research.postgres.test_private_asset_authority import _factor, _strategy

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


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
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == current_migrations()
    assets = _published_assets(postgres_dsn)

    factors = assets.list_current_factor_revisions()
    strategies = assets.list_current_strategy_revisions()

    assert [item.factor_id for item in factors] == ["private.factor.momentum"]
    assert [item.strategy_id for item in strategies] == ["private.strategy.momentum"]
