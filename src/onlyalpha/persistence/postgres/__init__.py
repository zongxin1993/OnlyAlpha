"""PostgreSQL operational persistence adapters."""

from .config import OnlyPostgresConfig as OnlyPostgresConfig
from .migration import (
    DEFAULT_MIGRATION_ROOT as DEFAULT_MIGRATION_ROOT,
)
from .migration import OnlyPostgresMigration as OnlyPostgresMigration
from .migration import OnlyPostgresMigrationAuthority as OnlyPostgresMigrationAuthority
from .migration import OnlyPostgresSchemaStatus as OnlyPostgresSchemaStatus
from .migration import OnlyPostgresSchemaVerdict as OnlyPostgresSchemaVerdict
from .migration import only_discover_postgres_migrations as only_discover_postgres_migrations
from .research_execution_store import OnlyPostgresResearchExecutionStore as OnlyPostgresResearchExecutionStore
from .research_operations_store import OnlyPostgresResearchOperationsStore as OnlyPostgresResearchOperationsStore
from .research_run_store import OnlyPostgresResearchRunStore as OnlyPostgresResearchRunStore
from .version import ONLYALPHA_POSTGRES_CLIENT_MAJOR as ONLYALPHA_POSTGRES_CLIENT_MAJOR
from .version import ONLYALPHA_POSTGRES_SERVER_MAJOR as ONLYALPHA_POSTGRES_SERVER_MAJOR
from .version import OnlyPostgresServerVersion as OnlyPostgresServerVersion
from .version import only_assert_supported_postgres_server as only_assert_supported_postgres_server
from .version import only_postgres_server_version as only_postgres_server_version

__all__ = [name for name in globals() if name.startswith(("Only", "only_", "DEFAULT_"))]
