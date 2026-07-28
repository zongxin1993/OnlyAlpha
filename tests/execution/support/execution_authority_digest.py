from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.execution import (
    OnlyAppliedProjectionRecord,
    OnlyCommittedExecutionTransaction,
    OnlyExecutionTransactionOutboxRecord,
)
from tests.execution.support.manager_authority_digest import OnlyTestRuntimeAuthorityDigest


@dataclass(frozen=True, slots=True)
class OnlyExecutionAuthorityDigest:
    managers: OnlyTestRuntimeAuthorityDigest
    applied_ledger: tuple[OnlyAppliedProjectionRecord, ...]
    transactions: tuple[OnlyCommittedExecutionTransaction, ...]
    outbox: tuple[OnlyExecutionTransactionOutboxRecord, ...]


__all__ = ["OnlyExecutionAuthorityDigest"]
