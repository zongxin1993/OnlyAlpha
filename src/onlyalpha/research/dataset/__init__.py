"""Public Historical Closed Bar Dataset v1 API."""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING

from .definition import (
    OnlyResearchDatasetDefinition,
    OnlyResearchDatasetQualityPolicy,
    OnlyResearchDatasetType,
)
from .lineage import (
    OnlyDatasetMaterialization,
    OnlyDatasetMaterializationStore,
    OnlyMarketDataRevisionBinding,
)
from .manifest import OnlyResearchDatasetProvenance, OnlyResearchDatasetSnapshot
from .ports import OnlyResearchDatasetSnapshotStore, OnlyResearchDatasetVerification, OnlyVerifiedResearchDataset
from .schema import OnlyResearchBarDatasetSchema
from .validation import OnlyResearchDatasetError

__all__ = [
    "OnlyParquetResearchDatasetSnapshotStore",
    "OnlyDatasetMaterialization",
    "OnlyDatasetMaterializationStore",
    "OnlyMarketDataRevisionBinding",
    "OnlyResearchBarDatasetSchema",
    "OnlyResearchDatasetDefinition",
    "OnlyResearchDatasetCorruptError",
    "OnlyResearchDatasetError",
    "OnlyResearchDatasetMaterializationPlan",
    "OnlyResearchDatasetMaterializer",
    "OnlyResearchDatasetNotFoundError",
    "OnlyResearchDatasetProvenance",
    "OnlyResearchDatasetQualityPolicy",
    "OnlyResearchDatasetSnapshot",
    "OnlyResearchDatasetSnapshotStore",
    "OnlyResearchDatasetStoreError",
    "OnlyResearchDatasetType",
    "OnlyResearchDatasetVerification",
    "OnlySealedMarketDataDatasetMaterializer",
    "OnlySealedMarketDataMaterializationPlan",
    "OnlySealedMarketDataMaterializationResult",
    "OnlyVerifiedResearchDataset",
]
if _TYPE_CHECKING:
    from .economic import OnlyEconomicFactManifest as OnlyEconomicFactManifest
    from .economic import OnlyResearchDatasetEconomicBinding as OnlyResearchDatasetEconomicBinding
    from .economic_store import OnlyDatasetEconomicBindingStore as OnlyDatasetEconomicBindingStore
    from .economic_store import OnlyDatasetEconomicBindingStoreError as OnlyDatasetEconomicBindingStoreError
    from .market_data_materializer import (
        OnlySealedMarketDataDatasetMaterializer as OnlySealedMarketDataDatasetMaterializer,
    )
    from .market_data_materializer import (
        OnlySealedMarketDataMaterializationPlan as OnlySealedMarketDataMaterializationPlan,
    )
    from .market_data_materializer import (
        OnlySealedMarketDataMaterializationResult as OnlySealedMarketDataMaterializationResult,
    )
    from .materializer import OnlyResearchDatasetMaterializer as OnlyResearchDatasetMaterializer
    from .parquet_store import OnlyParquetResearchDatasetSnapshotStore as OnlyParquetResearchDatasetSnapshotStore
    from .parquet_store import OnlyResearchDatasetCorruptError as OnlyResearchDatasetCorruptError
    from .parquet_store import OnlyResearchDatasetNotFoundError as OnlyResearchDatasetNotFoundError
    from .parquet_store import OnlyResearchDatasetStoreError as OnlyResearchDatasetStoreError
    from .plan import OnlyResearchDatasetMaterializationPlan as OnlyResearchDatasetMaterializationPlan

_LAZY_EXPORTS = {
    "OnlyParquetResearchDatasetSnapshotStore": ".parquet_store",
    "OnlyResearchDatasetCorruptError": ".parquet_store",
    "OnlyResearchDatasetNotFoundError": ".parquet_store",
    "OnlyResearchDatasetStoreError": ".parquet_store",
    "OnlySealedMarketDataDatasetMaterializer": ".market_data_materializer",
    "OnlySealedMarketDataMaterializationPlan": ".market_data_materializer",
    "OnlySealedMarketDataMaterializationResult": ".market_data_materializer",
    "OnlyResearchDatasetMaterializer": ".materializer",
    "OnlyResearchDatasetMaterializationPlan": ".plan",
    "OnlyEconomicFactManifest": ".economic",
    "OnlyResearchDatasetEconomicBinding": ".economic",
    "OnlyDatasetEconomicBindingStore": ".economic_store",
    "OnlyDatasetEconomicBindingStoreError": ".economic_store",
}


def __getattr__(name: str) -> object:
    module = _LAZY_EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(_import_module(module, __name__), name)
    globals()[name] = value
    return value
