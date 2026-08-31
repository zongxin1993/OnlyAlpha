"""Immutable exact lineage from sealed Market Data Revisions to Dataset content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from onlyalpha.canonical import only_canonical_fingerprint


@dataclass(frozen=True, slots=True)
class OnlyMarketDataRevisionBinding:
    source_id: str
    instrument_id: str
    data_kind: str
    revision_id: str
    revision_fingerprint: str

    def __post_init__(self) -> None:
        if not all(
            value.strip() for value in (self.source_id, self.instrument_id, self.data_kind, self.revision_id)
        ) or not _sha256(self.revision_fingerprint):
            raise ValueError("MARKET_DATA_REVISION_BINDING_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyDatasetMaterialization:
    materialization_id: str
    dataset_snapshot_fingerprint: str
    market_data_revision_bindings: tuple[OnlyMarketDataRevisionBinding, ...]
    materializer_id: str
    materializer_version: str
    request_fingerprint: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("DATASET_MATERIALIZATION_TIME_INVALID")
        if (
            not _sha256(self.dataset_snapshot_fingerprint)
            or not _sha256(self.request_fingerprint)
            or not self.market_data_revision_bindings
            or not self.materializer_id.strip()
            or not self.materializer_version.strip()
        ):
            raise ValueError("DATASET_MATERIALIZATION_INPUT_INVALID")
        expected = only_dataset_materialization_id(
            self.dataset_snapshot_fingerprint,
            self.market_data_revision_bindings,
            self.materializer_id,
            self.materializer_version,
            self.request_fingerprint,
        )
        if self.materialization_id != expected:
            raise ValueError("DATASET_MATERIALIZATION_IDENTITY_INVALID")

    def semantic_payload(self) -> dict[str, object]:
        return {
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "market_data_revision_bindings": self.market_data_revision_bindings,
            "materializer_id": self.materializer_id,
            "materializer_version": self.materializer_version,
            "request_fingerprint": self.request_fingerprint,
        }


class OnlyDatasetMaterializationStore(Protocol):
    def commit_materialization(self, value: OnlyDatasetMaterialization) -> OnlyDatasetMaterialization: ...

    def load_materialization(self, materialization_id: str) -> OnlyDatasetMaterialization: ...


def only_dataset_materialization_id(
    dataset_snapshot_fingerprint: str,
    bindings: tuple[OnlyMarketDataRevisionBinding, ...],
    materializer_id: str,
    materializer_version: str,
    request_fingerprint: str,
) -> str:
    ordered_bindings: tuple[OnlyMarketDataRevisionBinding, ...] = tuple(
        sorted(bindings, key=lambda item: (item.source_id, item.instrument_id, item.data_kind))
    )
    fingerprint = only_canonical_fingerprint(
        {
            "dataset_snapshot_fingerprint": dataset_snapshot_fingerprint,
            "market_data_revision_bindings": ordered_bindings,
            "materializer_id": materializer_id,
            "materializer_version": materializer_version,
            "request_fingerprint": request_fingerprint,
        }
    )
    return f"dataset-materialization:{fingerprint}"


def _sha256(value: str) -> bool:
    return len(value) == 64 and all(item in "0123456789abcdef" for item in value)


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
