"""Typed, mutually-exclusive external fee evidence scopes."""

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.fee.models import only_fee_fingerprint


class OnlyExternalFeeEvidenceScopeType(StrEnum):
    TRADE = "TRADE"
    ORDER = "ORDER"
    STATEMENT = "STATEMENT"


@dataclass(frozen=True, slots=True)
class OnlyFeeStatementScope(OnlyDomainModel):
    broker_id: str
    account_id: OnlyAccountId
    period_start: OnlyTimestamp
    period_end: OnlyTimestamp
    currency: OnlyCurrency
    statement_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.broker_id.strip() or not self.statement_id.strip() or self.period_end <= self.period_start:
            raise ValueError("FEE_STATEMENT_SCOPE_INVALID")
        if self.fingerprint != only_fee_fingerprint(self.authority_payload()):
            raise ValueError("FEE_STATEMENT_SCOPE_INVALID")

    @classmethod
    def create(
        cls,
        *,
        broker_id: str,
        account_id: OnlyAccountId,
        period_start: OnlyTimestamp,
        period_end: OnlyTimestamp,
        currency: OnlyCurrency,
        statement_id: str,
    ) -> "OnlyFeeStatementScope":
        payload = (
            broker_id,
            str(account_id),
            period_start.unix_nanos,
            period_end.unix_nanos,
            currency.to_dict(),
            statement_id,
        )
        return cls(
            broker_id,
            account_id,
            period_start,
            period_end,
            currency,
            statement_id,
            only_fee_fingerprint(payload),
        )

    def authority_payload(self) -> tuple[object, ...]:
        return (
            self.broker_id,
            str(self.account_id),
            self.period_start.unix_nanos,
            self.period_end.unix_nanos,
            self.currency.to_dict(),
            self.statement_id,
        )


@dataclass(frozen=True, slots=True)
class OnlyExternalFeeEvidenceScope(OnlyDomainModel):
    scope_type: OnlyExternalFeeEvidenceScopeType
    trade_id: OnlyTradeId | None = None
    order_id: OnlyOrderId | None = None
    statement: OnlyFeeStatementScope | None = None

    def __post_init__(self) -> None:
        populated = sum(value is not None for value in (self.trade_id, self.order_id, self.statement))
        valid = (
            populated == 1
            and (self.scope_type is not OnlyExternalFeeEvidenceScopeType.TRADE or self.trade_id is not None)
            and (self.scope_type is not OnlyExternalFeeEvidenceScopeType.ORDER or self.order_id is not None)
            and (self.scope_type is not OnlyExternalFeeEvidenceScopeType.STATEMENT or self.statement is not None)
        )
        if not valid:
            raise ValueError("FEE_EVIDENCE_SCOPE_INVALID")

    @classmethod
    def trade(cls, trade_id: OnlyTradeId) -> "OnlyExternalFeeEvidenceScope":
        return cls(OnlyExternalFeeEvidenceScopeType.TRADE, trade_id=trade_id)

    @classmethod
    def order(cls, order_id: OnlyOrderId) -> "OnlyExternalFeeEvidenceScope":
        return cls(OnlyExternalFeeEvidenceScopeType.ORDER, order_id=order_id)

    @classmethod
    def statement_period(cls, statement: OnlyFeeStatementScope) -> "OnlyExternalFeeEvidenceScope":
        return cls(OnlyExternalFeeEvidenceScopeType.STATEMENT, statement=statement)

    @property
    def fingerprint(self) -> str:
        return only_fee_fingerprint(self.to_dict())


__all__ = [name for name in globals() if name.startswith("Only")]
