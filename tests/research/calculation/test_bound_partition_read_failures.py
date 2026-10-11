"""Unavailable retained partition bytes cannot be misclassified as corrupt facts."""

import errno
import os

import pytest

from onlyalpha.research._durability import _OnlyBoundPublicationTree
from onlyalpha.research.calculation.errors import OnlyResearchCalculationResultStoreError
from onlyalpha.research.dataset import parquet_store
from onlyalpha.research.dataset.parquet_store import OnlyResearchDatasetStoreError
from tests.research.artifact.test_calculation_v2 import _publication

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("owner", ["dataset", "calculation"])
@pytest.mark.parametrize("fault", [errno.EIO, errno.EACCES])
@pytest.mark.parametrize("phase", ["read", "exit"])
def test_retained_partition_io_remains_unavailable(tmp_path, monkeypatch, owner, fault, phase):
    _, _, _, selection, _, evidence = _publication(tmp_path)
    calculations = evidence._result_store
    calculation = calculations.load_verified(selection[0][0])
    manifest = calculation.manifest
    datasets = calculations._dataset_store
    snapshot = datasets.load(manifest.dataset_snapshot_fingerprint)
    partition = datasets._target(snapshot.snapshot_fingerprint) / snapshot.partitions[0].relative_path
    identity = partition.stat()
    enabled = phase == "read"
    descriptor_read = parquet_store._read_descriptor
    tree_read = _OnlyBoundPublicationTree.read_bytes

    def dataset_failure(descriptor, limit):
        actual = os.fstat(descriptor)
        if owner == "dataset" and enabled and (actual.st_dev, actual.st_ino) == (identity.st_dev, identity.st_ino):
            raise OSError(fault, "controlled partition I/O failure")
        return descriptor_read(descriptor, limit)

    def calculation_failure(self, relative):
        if (
            owner == "calculation"
            and enabled
            and self.target == calculations._target(manifest.calculation_fingerprint)
            and relative.endswith(".parquet")
        ):
            raise OSError(fault, "controlled partition I/O failure")
        return tree_read(self, relative)

    monkeypatch.setattr(parquet_store, "_read_descriptor", dataset_failure)
    monkeypatch.setattr(_OnlyBoundPublicationTree, "read_bytes", calculation_failure)
    session = (
        datasets.inspect_verified_table(snapshot.snapshot_fingerprint)
        if owner == "dataset"
        else calculations.inspect_verified(manifest.calculation_fingerprint)
    )
    error = OnlyResearchDatasetStoreError if owner == "dataset" else OnlyResearchCalculationResultStoreError
    expected = "DATASET_STORE_UNAVAILABLE" if owner == "dataset" else "RESULT_STORE_UNAVAILABLE"
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(error, match=expected):
        with session:
            enabled = True
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
