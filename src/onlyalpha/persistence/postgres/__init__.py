"""PostgreSQL operational persistence adapters."""

from .backtest_store import OnlyPostgresBacktestStore as OnlyPostgresBacktestStore
from .config import OnlyPostgresConfig as OnlyPostgresConfig
from .config import OnlyPostgresOperationalConnectionOptions as OnlyPostgresOperationalConnectionOptions
from .config import only_assert_postgres_test_database as only_assert_postgres_test_database
from .kernel_authority import OnlyPostgresKernelAuthorityGuard as OnlyPostgresKernelAuthorityGuard
from .market_data_catalog import OnlyPostgresMarketDataCatalog as OnlyPostgresMarketDataCatalog
from .migration import (
    DEFAULT_MIGRATION_ROOT as DEFAULT_MIGRATION_ROOT,
)
from .migration import OnlyPostgresMigration as OnlyPostgresMigration
from .migration import OnlyPostgresSchemaStatus as OnlyPostgresSchemaStatus
from .migration import OnlyPostgresSchemaVerdict as OnlyPostgresSchemaVerdict
from .migration import OnlyPostgresSchemaVerifier as OnlyPostgresSchemaVerifier
from .migration import only_discover_postgres_migrations as only_discover_postgres_migrations
from .research_deployment_store import (
    OnlyPostgresResearchDeploymentStore as OnlyPostgresResearchDeploymentStore,
)
from .research_execution_store import OnlyPostgresResearchExecutionStore as OnlyPostgresResearchExecutionStore
from .research_operations_store import OnlyPostgresResearchOperationsStore as OnlyPostgresResearchOperationsStore
from .research_run_store import OnlyPostgresResearchRunStore as OnlyPostgresResearchRunStore
from .version import ONLYALPHA_POSTGRES_CLIENT_MAJOR as ONLYALPHA_POSTGRES_CLIENT_MAJOR
from .version import ONLYALPHA_POSTGRES_SERVER_MAJOR as ONLYALPHA_POSTGRES_SERVER_MAJOR
from .version import OnlyPostgresServerVersion as OnlyPostgresServerVersion
from .version import only_assert_supported_postgres_server as only_assert_supported_postgres_server
from .version import only_postgres_server_version as only_postgres_server_version

__all__ = [name for name in globals() if name.startswith(("Only", "only_", "DEFAULT_"))]
