"""Immutable Dataset Snapshot store contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.domain.market import OnlyBar

from .manifest import OnlyResearchDatasetSnapshot


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetVerification:
    valid: bool
    snapshot_fingerprint: str
    row_count: int


class OnlyResearchDatasetSnapshotStore(Protocol):
    def commit(
        self,
        snapshot: OnlyResearchDatasetSnapshot,
        partitions: tuple[tuple[OnlyBar, ...], ...],
    ) -> OnlyResearchDatasetSnapshot: ...

    def load(self, snapshot_fingerprint: str) -> OnlyResearchDatasetSnapshot: ...

    def load_bars(self, snapshot_fingerprint: str) -> tuple[OnlyBar, ...]: ...

    def verify(self, snapshot_fingerprint: str) -> OnlyResearchDatasetVerification: ...

    def exists(self, snapshot_fingerprint: str) -> bool: ...
