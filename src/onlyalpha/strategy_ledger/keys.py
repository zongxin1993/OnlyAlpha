"""Strategy Ledger scope key."""

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.value import OnlyCurrency


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerKey(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    base_currency: OnlyCurrency
