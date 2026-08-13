"""Immutable Dataset Snapshot store contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.domain.market import OnlyBar

from .manifest import OnlyResearchDatasetSnapshot


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetVerification:
    valid: bool
    snapshot_fingerprint: str
    row_count: int


@dataclass(frozen=True, slots=True)
class OnlyVerifiedResearchDataset:
    """A snapshot and columnar payload admitted through full store verification."""

    snapshot: OnlyResearchDatasetSnapshot
    table: pa.Table


class OnlyResearchDatasetSnapshotStore(Protocol):
    def commit(
        self,
        snapshot: OnlyResearchDatasetSnapshot,
        partitions: tuple[tuple[OnlyBar, ...], ...],
    ) -> OnlyResearchDatasetSnapshot: ...

    def load(self, snapshot_fingerprint: str) -> OnlyResearchDatasetSnapshot: ...

    def load_bars(self, snapshot_fingerprint: str) -> tuple[OnlyBar, ...]: ...

    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset: ...

    def verify(self, snapshot_fingerprint: str) -> OnlyResearchDatasetVerification: ...

    def exists(self, snapshot_fingerprint: str) -> bool: ...
