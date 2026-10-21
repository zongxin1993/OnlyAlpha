"""Materialize native replay inputs through verified immutable Dataset owners."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.research.dataset.codec import only_table_to_bars
from onlyalpha.research.dataset.ports import OnlyBoundedResearchDatasetSnapshotStore
from onlyalpha_calculation_worker.contracts import integer, sha

if TYPE_CHECKING:
    from onlyalpha.backtest.admission import OnlyBacktestDatasetBindingReader


def load_dataset_inputs(
    datasets: OnlyBoundedResearchDatasetSnapshotStore,
    bindings: OnlyBacktestDatasetBindingReader,
    binding_fingerprint: str,
    source: str,
    data_version: str,
    priority: int,
    market_product: str,
) -> dict[str, Any]:
    """Trusted Application input adapter, not Product admission or producer authentication."""
    sha(source)
    sha(market_product)
    integer(priority, maximum=2**32 - 1)
    version = str(OnlyDataVersion(data_version))
    if len(version) > 256:
        raise ValueError("BACKTEST_DATA_VERSION_BOUND")
    binding = bindings.load_verified(sha(binding_fingerprint))
    if binding.economic_facts or binding.market_product_composition_fingerprint != market_product:
        raise ValueError("BACKTEST_DATASET_BINDING_UNSUPPORTED")
    verified = datasets.bounded(max_rows=65536, max_bytes=128 * 1024 * 1024).load_verified_table(
        binding.base_dataset_snapshot_fingerprint
    )
    # Decode the already verified table. A second independent load cannot replace its proof.
    bars = only_table_to_bars(verified.table)
    if len(bars) != verified.snapshot.row_count or len(bars) > 65536:
        raise ValueError("BACKTEST_DATASET_COMPLETENESS")
    records = []
    for index, bar in enumerate(bars, 1):
        if (
            not bar.is_closed
            or bar.revision != 0
            or bar.adjustment_type.value != "RAW"
            or bar.ts_event != bar.bar_end
            or bar.ts_init < bar.ts_event
        ):
            raise ValueError("BACKTEST_DATASET_BAR_UNSUPPORTED")
        records.append(
            {"schema_version": 1, "source": source, "sequence": index, "data_version": version, "bar": bar.to_dict()}
        )
    return {
        "schema_version": 1,
        "sources": [
            {
                "schema_version": 1,
                "source": source,
                "snapshot": verified.snapshot.snapshot_fingerprint,
                "dataset_binding": binding.fingerprint,
                "data_version": version,
                "priority": priority,
                "rows": len(records),
            }
        ],
        "records": records,
    }
