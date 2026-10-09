"""Installed-test composition of real PostgreSQL owning input readers."""

import runpy
from pathlib import Path

from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationInputVerifier
from onlyalpha.application.chart_calculation_input_export import OnlyChartCalculationInputExportService
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
    OnlyPostgresChartCalculationCompilationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_preparation_store import (
    OnlyPostgresChartCalculationPreparationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore
from onlyalpha.persistence.postgres.market_data_catalog import OnlyPostgresMarketDataCatalog
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore


def export_input(dsn, operation_id, dataset_root, facts_path, registry):
    datasets = OnlyParquetResearchDatasetSnapshotStore(Path(dataset_root))
    reader = runpy.run_path(str(Path(__file__).with_name("market_fact_reference.py")))["ReferenceFactReader"]
    return OnlyChartCalculationInputExportService(
        operations=OnlyPostgresChartCalculationAdmissionStore(dsn),
        preparations=OnlyPostgresChartCalculationPreparationStore(dsn),
        compilations=OnlyPostgresChartCalculationCompilationStore(dsn),
        inputs=OnlyChartCalculationInputVerifier(
            datasets=datasets, materializations=datasets, runtime_generations=registry
        ),
        integrations=OnlyPostgresIntegrationStore(dsn),
        catalog=OnlyPostgresMarketDataCatalog(dsn),
        facts=reader(Path(facts_path)),
        materializations=datasets,
    ).export(OnlyProductCommandId(operation_id))
