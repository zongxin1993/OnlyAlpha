"""Exact local fee-fact scope authority for reconciliation."""

from typing import Protocol

from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.fee.evidence import OnlyExternalFeeEvidence
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScopeType
from onlyalpha.fee.ledger import OnlyFeeApplicationLedger, OnlyFeeApplicationRecord
from onlyalpha.fee.models import only_fee_fingerprint


class OnlyFeeReconciliationLocalFactQuery(Protocol):
    def query(self, evidence: OnlyExternalFeeEvidence) -> tuple[OnlyFeeApplicationRecord, ...]: ...

    def fingerprint(self, records: tuple[OnlyFeeApplicationRecord, ...]) -> str: ...


class OnlyFeeApplicationLocalFactQuery:
    def __init__(self, ledger: OnlyFeeApplicationLedger, *, broker_id: str, account_id: OnlyAccountId) -> None:
        self._ledger = ledger
        self._broker_id = broker_id
        self._account_id = account_id

    def query(self, evidence: OnlyExternalFeeEvidence) -> tuple[OnlyFeeApplicationRecord, ...]:
        if evidence.account_id != self._account_id:
            raise ValueError("FEE_EVIDENCE_ACCOUNT_AUTHORITY_CONFLICT")
        if evidence.broker_id != self._broker_id:
            raise ValueError("FEE_EVIDENCE_BROKER_AUTHORITY_CONFLICT")
        scope = evidence.scope
        if scope.scope_type is OnlyExternalFeeEvidenceScopeType.TRADE:
            if scope.trade_id is None:
                raise ValueError("FEE_EVIDENCE_SCOPE_INVALID")
            selected = self._ledger.query_trade(evidence.account_id, scope.trade_id)
        elif scope.scope_type is OnlyExternalFeeEvidenceScopeType.ORDER:
            if scope.order_id is None:
                raise ValueError("FEE_EVIDENCE_SCOPE_INVALID")
            selected = self._ledger.query_order(evidence.account_id, scope.order_id)
        else:
            statement = scope.statement
            if statement is None:
                raise ValueError("FEE_EVIDENCE_SCOPE_INVALID")
            if statement.broker_id != self._broker_id or statement.account_id != self._account_id:
                raise ValueError("FEE_RECONCILIATION_LOCAL_FACT_SCOPE_CONFLICT")
            selected = self._ledger.query_statement(
                statement.account_id,
                statement.currency,
                statement.period_start,
                statement.period_end,
            )
        if any(item.incremental_amount.currency != evidence.currency for item in selected):
            raise ValueError("FEE_EVIDENCE_CURRENCY_CONFLICT")
        return tuple(sorted(selected, key=lambda item: (item.effective_at.unix_nanos, item.sequence, item.record_id)))

    @staticmethod
    def fingerprint(records: tuple[OnlyFeeApplicationRecord, ...]) -> str:
        return only_fee_fingerprint(tuple(item.to_dict() for item in records))


__all__ = ["OnlyFeeApplicationLocalFactQuery", "OnlyFeeReconciliationLocalFactQuery"]
