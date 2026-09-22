"""One-shot development bootstrap using the existing database authorities."""

from __future__ import annotations

import json
import os
from pathlib import Path

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.clickhouse import (
    OnlyClickHouseClient,
    OnlyClickHouseConfig,
    OnlyClickHouseMigrationAuthority,
)
from onlyalpha.persistence.postgres import (
    MASTER_KEY_FILE,
    OnlyPostgresConfig,
    only_ensure_dev_master_key,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority


def main() -> int:
    if __package__:
        from scripts.agent_provider_bootstrap import only_provision_dev_agent_authority
        from scripts.database import _initialize_deployment, _validate
    else:
        from agent_provider_bootstrap import only_provision_dev_agent_authority

        from database import _initialize_deployment, _validate

    postgres_dsn = OnlyPostgresConfig.from_environment().dsn
    clickhouse = OnlyClickHouseMigrationAuthority(OnlyClickHouseClient(OnlyClickHouseConfig.from_environment()))
    user_data_root = Path(os.environ.get("ONLYALPHA_USER_DATA_ROOT", "/var/lib/onlyalpha"))
    if not user_data_root.is_absolute():
        raise ValueError("ONLYALPHA_USER_DATA_ROOT must be absolute")

    applied_postgres = OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    applied_clickhouse = clickhouse.migrate()
    deployment_id = _initialize_deployment(postgres_dsn, user_data_root)
    _validate(postgres_dsn, None)
    clickhouse.validate()
    only_ensure_dev_master_key(OnlyUserDataLayout(user_data_root).root / MASTER_KEY_FILE)
    agent_authority = only_provision_dev_agent_authority(
        postgres_dsn=postgres_dsn,
        user_data_root=user_data_root,
        provider_base_url=os.environ.get("ONLYALPHA_AGENT_PROVIDER_BASE_URL", "http://agent-provider-fixture:8080/v1"),
        provider_api_credential=os.environ.get("ONLYALPHA_AGENT_PROVIDER_TOKEN", "onlyalpha-dev-agent-provider-secret"),
        model_id=os.environ.get("ONLYALPHA_AGENT_PROVIDER_MODEL_ID", "onlyalpha-dev-model"),
        model_version=os.environ.get("ONLYALPHA_AGENT_PROVIDER_MODEL_VERSION", "1.0.0"),
    )
    print(
        json.dumps(
            {
                "bootstrap": "READY",
                "deployment_id": deployment_id,
                "postgres_migrations": applied_postgres,
                "clickhouse_migrations": applied_clickhouse,
                "agent_provider": agent_authority.summary_document(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
