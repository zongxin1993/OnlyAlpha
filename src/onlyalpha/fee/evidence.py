"""Immutable external broker fee evidence and append-only identity authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeType, only_fee_fingerprint


class OnlyExternalFeeEvidenceMode(StrEnum):
    COMMISSION_ONLY = "COMMISSION_ONLY"
    DETAILED = "DETAILED"
    ALL_IN = "ALL_IN"
    ORDER_CUMULATIVE = "ORDER_CUMULATIVE"
    DEFERRED_STATEMENT = "DEFERRED_STATEMENT"


class OnlyExternalFeeEvidenceScope(StrEnum):
    TRADE = "TRADE"
    ORDER = "ORDER"
    STATEMENT = "STATEMENT"


@dataclass(frozen=True, slots=True)
class OnlyExternalFeeComponent(OnlyDomainModel):
    external_component_id: str
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    amount: OnlyMoney

    def __post_init__(self) -> None:
        if not self.external_component_id.strip() or self.amount.amount < 0:
            raise ValueError("external fee component identity/amount is invalid")


@dataclass(frozen=True, slots=True)
class OnlyExternalFeeEvidence(OnlyDomainModel):
    evidence_id: str
    broker_id: str
    account_id: OnlyAccountId
    scope: OnlyExternalFeeEvidenceScope
    mode: OnlyExternalFeeEvidenceMode
    external_reference: str
    report_version: str
    content_fingerprint: str
    trade_id: OnlyTradeId | None
    order_id: OnlyOrderId | None
    statement_scope: str | None
    reported_total: OnlyMoney | None
    reported_components: tuple[OnlyExternalFeeComponent, ...]
    effective_at: OnlyTimestamp
    received_at: OnlyTimestamp

    def __post_init__(self) -> None:
        if not all(
            (
                self.evidence_id.strip(),
                self.broker_id.strip(),
                self.external_reference.strip(),
                self.report_version.strip(),
            )
        ):
            raise ValueError("external fee evidence identity cannot be empty")
        if self.scope is OnlyExternalFeeEvidenceScope.TRADE and self.trade_id is None:
            raise ValueError("TRADE fee evidence requires trade_id")
        if self.scope is OnlyExternalFeeEvidenceScope.ORDER and self.order_id is None:
            raise ValueError("ORDER fee evidence requires order_id")
        if self.scope is OnlyExternalFeeEvidenceScope.STATEMENT and not (self.statement_scope or "").strip():
            raise ValueError("STATEMENT fee evidence requires statement_scope")
        if self.mode is OnlyExternalFeeEvidenceMode.DETAILED and not self.reported_components:
            raise ValueError("DETAILED fee evidence requires components")
        if self.mode is not OnlyExternalFeeEvidenceMode.DETAILED and self.reported_total is None:
            raise ValueError("aggregate fee evidence requires reported_total")
        monies = tuple(item.amount for item in self.reported_components) + (
            () if self.reported_total is None else (self.reported_total,)
        )
        if any(item.amount < 0 for item in monies) or len({item.currency for item in monies}) > 1:
            raise ValueError("external fee evidence currency/amount is invalid")
        expected = only_fee_fingerprint(self.content_payload())
        if self.content_fingerprint != expected:
            raise ValueError("EXTERNAL_FEE_EVIDENCE_CONTENT_FINGERPRINT_CONFLICT")

    @classmethod
    def create(
        cls,
        *,
        broker_id: str,
        account_id: OnlyAccountId,
        scope: OnlyExternalFeeEvidenceScope,
        mode: OnlyExternalFeeEvidenceMode,
        external_reference: str,
        report_version: str,
        trade_id: OnlyTradeId | None,
        order_id: OnlyOrderId | None,
        statement_scope: str | None,
        reported_total: OnlyMoney | None,
        reported_components: tuple[OnlyExternalFeeComponent, ...],
        effective_at: OnlyTimestamp,
        received_at: OnlyTimestamp,
    ) -> OnlyExternalFeeEvidence:
        payload = (
            broker_id,
            str(account_id),
            scope.value,
            mode.value,
            external_reference,
            report_version,
            None if trade_id is None else str(trade_id),
            None if order_id is None else str(order_id),
            statement_scope,
            None if reported_total is None else reported_total.to_dict(),
            tuple(item.to_dict() for item in reported_components),
            effective_at.to_dict(),
        )
        fingerprint = only_fee_fingerprint(payload)
        evidence_id = only_fee_fingerprint(
            (broker_id, str(account_id), external_reference, report_version, fingerprint)
        )
        return cls(
            evidence_id,
            broker_id,
            account_id,
            scope,
            mode,
            external_reference,
            report_version,
            fingerprint,
            trade_id,
            order_id,
            statement_scope,
            reported_total,
            reported_components,
            effective_at,
            received_at,
        )

    def content_payload(self) -> tuple[object, ...]:
        return (
            self.broker_id,
            str(self.account_id),
            self.scope.value,
            self.mode.value,
            self.external_reference,
            self.report_version,
            None if self.trade_id is None else str(self.trade_id),
            None if self.order_id is None else str(self.order_id),
            self.statement_scope,
            None if self.reported_total is None else self.reported_total.to_dict(),
            tuple(item.to_dict() for item in self.reported_components),
            self.effective_at.to_dict(),
        )


class OnlyExternalFeeEvidenceLedger:
    def __init__(self) -> None:
        self._items: dict[str, OnlyExternalFeeEvidence] = {}
        self._identity: dict[tuple[str, OnlyAccountId, str, str], str] = {}

    @property
    def evidence(self) -> tuple[OnlyExternalFeeEvidence, ...]:
        return tuple(sorted(self._items.values(), key=lambda item: (item.received_at.unix_nanos, item.evidence_id)))

    def classify(self, evidence: OnlyExternalFeeEvidence) -> str | None:
        key = (evidence.broker_id, evidence.account_id, evidence.external_reference, evidence.report_version)
        current = self._identity.get(key)
        if current is None:
            return None
        return (
            "DUPLICATE_EVIDENCE"
            if current == evidence.content_fingerprint
            else "EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT"
        )

    def apply(self, evidence: OnlyExternalFeeEvidence) -> bool:
        classification = self.classify(evidence)
        if classification == "DUPLICATE_EVIDENCE":
            return False
        if classification is not None:
            raise ValueError(classification)
        key = (evidence.broker_id, evidence.account_id, evidence.external_reference, evidence.report_version)
        self._identity[key] = evidence.content_fingerprint
        self._items[evidence.evidence_id] = evidence
        return True


__all__ = [name for name in globals() if name.startswith("Only")]
