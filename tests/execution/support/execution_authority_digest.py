from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.execution import (
    OnlyAppliedRuntimeProjectionRecord,
    OnlyCommittedRuntimeTransaction,
    OnlyRuntimeTransactionOutboxRecord,
)
from tests.execution.support.manager_authority_digest import OnlyTestRuntimeAuthorityDigest


@dataclass(frozen=True, slots=True)
class OnlyExecutionAuthorityDigest:
    managers: OnlyTestRuntimeAuthorityDigest
    applied_ledger: tuple[OnlyAppliedRuntimeProjectionRecord, ...]
    transactions: tuple[OnlyCommittedRuntimeTransaction, ...]
    outbox: tuple[OnlyRuntimeTransactionOutboxRecord, ...]


__all__ = ["OnlyExecutionAuthorityDigest"]
