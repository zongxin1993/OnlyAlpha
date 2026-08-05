"""Operation-neutral fact contracts for the Runtime transaction kernel."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp


class OnlyRuntimeFactDraft(Protocol):
    @property
    def runtime_id(self) -> OnlyRuntimeId: ...

    @property
    def account_id(self) -> OnlyAccountId: ...

    @property
    def ts_event(self) -> OnlyTimestamp: ...

    def finalize(self, execution_sequence: int, committed_at: OnlyTimestamp) -> OnlyCommittedRuntimeFact: ...

    def to_dict(self) -> dict[str, object]: ...


class OnlyCommittedRuntimeFact(Protocol):
    @property
    def runtime_id(self) -> OnlyRuntimeId: ...

    @property
    def account_id(self) -> OnlyAccountId: ...

    @property
    def execution_sequence(self) -> int: ...

    @property
    def ts_committed(self) -> OnlyTimestamp: ...

    def to_dict(self) -> dict[str, object]: ...


__all__ = ["OnlyCommittedRuntimeFact", "OnlyRuntimeFactDraft"]
