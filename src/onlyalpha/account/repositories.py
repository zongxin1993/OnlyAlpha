"""Account repository port and deterministic in-memory implementation."""

from typing import Protocol

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId


class OnlyAccountRepository(Protocol):
    def save(self, snapshot: OnlyAccountSnapshot) -> None: ...

    def get(self, account_id: OnlyAccountId) -> OnlyAccountSnapshot | None: ...

    def replace_execution_authority(self, snapshot: OnlyAccountSnapshot) -> None: ...


class OnlyInMemoryAccountRepository:
    def __init__(self) -> None:
        self._snapshots: dict[OnlyAccountId, OnlyAccountSnapshot] = {}

    def save(self, snapshot: OnlyAccountSnapshot) -> None:
        self._snapshots[snapshot.account_id] = snapshot

    def get(self, account_id: OnlyAccountId) -> OnlyAccountSnapshot | None:
        return self._snapshots.get(account_id)

    def replace_execution_authority(self, snapshot: OnlyAccountSnapshot) -> None:
        snapshots = dict(self._snapshots)
        snapshots[snapshot.account_id] = snapshot
        self._snapshots = snapshots
