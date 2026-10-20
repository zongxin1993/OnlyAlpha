import pytest
from onlyalpha_calculation_worker.backtest_dataset import load_dataset_inputs

from onlyalpha.research.dataset import OnlyDatasetEconomicBindingStore, OnlyResearchDatasetEconomicBinding
from onlyalpha.research.dataset.parquet_store import (
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchDatasetStoreError,
)
from tests.research.dataset.test_store_contract import _snapshot


def test_real_verified_parquet_dataset_is_the_input_owner(tmp_path):
    datasets = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "datasets")
    snapshot, partitions = _snapshot()
    snapshot = datasets.commit(snapshot, partitions)
    bindings = OnlyDatasetEconomicBindingStore(tmp_path / "bindings")
    binding = bindings.publish_verified(OnlyResearchDatasetEconomicBinding(snapshot.snapshot_fingerprint, "b" * 64, ()))
    value = load_dataset_inputs(datasets, bindings, binding.fingerprint, "a" * 64, "opaque-v1", 0, "b" * 64)
    assert value["sources"][0]["snapshot"] == snapshot.snapshot_fingerprint
    assert value["sources"][0]["dataset_binding"] == binding.fingerprint
    assert value["records"][0]["data_version"] == "opaque-v1"
    assert value["records"][0]["bar"] == partitions[0][0].to_dict()
    with pytest.raises(ValueError, match="BINDING"):
        load_dataset_inputs(datasets, bindings, binding.fingerprint, "a" * 64, "opaque-v1", 0, "c" * 64)
    # Exact owning store layout is observed rather than assumed.
    file = next((tmp_path / "datasets").rglob("*.parquet"))
    file.write_bytes(b"corrupt")
    with pytest.raises(OnlyResearchDatasetStoreError):
        load_dataset_inputs(datasets, bindings, binding.fingerprint, "a" * 64, "opaque-v1", 0, "b" * 64)
