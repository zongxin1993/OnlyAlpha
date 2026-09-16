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
        from scripts.database import _initialize_deployment, _validate
    else:
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
    print(
        json.dumps(
            {
                "bootstrap": "READY",
                "deployment_id": deployment_id,
                "postgres_migrations": applied_postgres,
                "clickhouse_migrations": applied_clickhouse,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
