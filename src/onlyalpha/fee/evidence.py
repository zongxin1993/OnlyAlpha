"""Immutable normalized broker fee evidence and revision lineage."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScope
from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeEconomicDirection, OnlyFeeType, only_fee_fingerprint


class OnlyExternalFeeEvidenceMode(StrEnum):
    COMMISSION_ONLY = "COMMISSION_ONLY"
    DETAILED = "DETAILED"
    ALL_IN = "ALL_IN"
    ORDER_CUMULATIVE = "ORDER_CUMULATIVE"
    DEFERRED_STATEMENT = "DEFERRED_STATEMENT"


@dataclass(frozen=True, order=True, slots=True)
class OnlyFeeReconciliationComponentIdentity(OnlyDomainModel):
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    economic_direction: OnlyFeeEconomicDirection
    normalized_component_id: str

    def __post_init__(self) -> None:
        if not self.normalized_component_id.strip():
            raise ValueError("fee reconciliation component identity cannot be empty")

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return (
            self.fee_type.value,
            self.authority.value,
            self.economic_direction.value,
            self.normalized_component_id,
        )


@dataclass(frozen=True, slots=True)
class OnlyExternalFeeComponent(OnlyDomainModel):
    component_identity: OnlyFeeReconciliationComponentIdentity
    amount: OnlyMoney
    fingerprint: str

    def __post_init__(self) -> None:
        if self.amount.amount < 0 or self.fingerprint != only_fee_fingerprint(
            (self.component_identity.to_dict(), self.amount.to_dict())
        ):
            raise ValueError("external fee component is invalid")

    @classmethod
    def create(
        cls, component_identity: OnlyFeeReconciliationComponentIdentity, amount: OnlyMoney
    ) -> OnlyExternalFeeComponent:
        return cls(
            component_identity,
            amount,
            only_fee_fingerprint((component_identity.to_dict(), amount.to_dict())),
        )


@dataclass(frozen=True, slots=True)
class OnlyExternalFeeEvidenceFamilyIdentity(OnlyDomainModel):
    broker_id: str
    account_id: OnlyAccountId
    external_reference: str
    scope_fingerprint: str
    fingerprint: str

    def __post_init__(self) -> None:
        payload = (self.broker_id, str(self.account_id), self.external_reference, self.scope_fingerprint)
        if (
            not self.broker_id.strip()
            or not self.external_reference.strip()
            or self.fingerprint != only_fee_fingerprint(payload)
        ):
            raise ValueError("EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT")


@dataclass(frozen=True, slots=True)
class OnlyExternalFeeEvidence(OnlyDomainModel):
    schema_version = 2

    evidence_id: str
    broker_id: str
    account_id: OnlyAccountId
    scope: OnlyExternalFeeEvidenceScope
    mode: OnlyExternalFeeEvidenceMode
    external_reference: str
    report_version: str
    revision_sequence: int
    supersedes_evidence_id: str | None
    content_fingerprint: str
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
        if self.revision_sequence < 1 or (self.revision_sequence == 1) != (self.supersedes_evidence_id is None):
            raise ValueError("EXTERNAL_FEE_EVIDENCE_REVISION_INVALID")
        ordered = tuple(sorted(self.reported_components, key=lambda item: item.component_identity.sort_key))
        if ordered != self.reported_components:
            raise ValueError("external fee components must use deterministic order")
        identities = tuple(item.component_identity for item in ordered)
        if len(set(identities)) != len(identities):
            raise ValueError("FEE_COMPONENT_MAPPING_AMBIGUOUS")
        if self.mode is OnlyExternalFeeEvidenceMode.DETAILED and not ordered:
            raise ValueError("FEE_COMPONENT_INCOMPLETE")
        if self.mode is not OnlyExternalFeeEvidenceMode.DETAILED and self.reported_total is None:
            raise ValueError("aggregate fee evidence requires reported_total")
        monies = tuple(item.amount for item in ordered) + (
            () if self.reported_total is None else (self.reported_total,)
        )
        if any(item.amount < 0 for item in monies) or len({item.currency for item in monies}) > 1:
            raise ValueError("FEE_EVIDENCE_CURRENCY_CONFLICT")
        if self.mode is OnlyExternalFeeEvidenceMode.DETAILED and self.reported_total is not None:
            signed = sum(
                (
                    item.amount.amount
                    if item.component_identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
                    else -item.amount.amount
                    for item in ordered
                ),
                Decimal(0),
            )
            if signed != self.reported_total.amount:
                raise ValueError("EXTERNAL_FEE_EVIDENCE_INTERNAL_CONFLICT")
        if self.scope.statement is not None:
            statement = self.scope.statement
            if statement.broker_id != self.broker_id or statement.account_id != self.account_id:
                raise ValueError("FEE_EVIDENCE_SCOPE_INVALID")
            if monies and any(item.currency != statement.currency for item in monies):
                raise ValueError("FEE_EVIDENCE_CURRENCY_CONFLICT")
        if self.content_fingerprint != only_fee_fingerprint(self.content_payload()):
            raise ValueError("EXTERNAL_FEE_EVIDENCE_CONTENT_FINGERPRINT_CONFLICT")
        expected_id = only_fee_fingerprint(
            (self.family_identity.fingerprint, self.revision_sequence, self.report_version, self.content_fingerprint)
        )
        if self.evidence_id != expected_id:
            raise ValueError("EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT")

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
        revision_sequence: int,
        supersedes_evidence_id: str | None,
        reported_total: OnlyMoney | None,
        reported_components: tuple[OnlyExternalFeeComponent, ...],
        effective_at: OnlyTimestamp,
        received_at: OnlyTimestamp,
    ) -> OnlyExternalFeeEvidence:
        components = tuple(sorted(reported_components, key=lambda item: item.component_identity.sort_key))
        family_payload = (broker_id, str(account_id), external_reference, scope.fingerprint)
        family_fingerprint = only_fee_fingerprint(family_payload)
        payload = (
            broker_id,
            str(account_id),
            scope.to_dict(),
            mode.value,
            external_reference,
            report_version,
            revision_sequence,
            supersedes_evidence_id,
            None if reported_total is None else reported_total.to_dict(),
            tuple(item.to_dict() for item in components),
            effective_at.to_dict(),
        )
        content_fingerprint = only_fee_fingerprint(payload)
        evidence_id = only_fee_fingerprint((family_fingerprint, revision_sequence, report_version, content_fingerprint))
        return cls(
            evidence_id,
            broker_id,
            account_id,
            scope,
            mode,
            external_reference,
            report_version,
            revision_sequence,
            supersedes_evidence_id,
            content_fingerprint,
            reported_total,
            components,
            effective_at,
            received_at,
        )

    @property
    def family_identity(self) -> OnlyExternalFeeEvidenceFamilyIdentity:
        payload = (self.broker_id, str(self.account_id), self.external_reference, self.scope.fingerprint)
        return OnlyExternalFeeEvidenceFamilyIdentity(
            self.broker_id,
            self.account_id,
            self.external_reference,
            self.scope.fingerprint,
            only_fee_fingerprint(payload),
        )

    @property
    def currency(self) -> OnlyCurrency:
        if self.reported_total is not None:
            return self.reported_total.currency
        return self.reported_components[0].amount.currency

    def content_payload(self) -> tuple[object, ...]:
        return (
            self.broker_id,
            str(self.account_id),
            self.scope.to_dict(),
            self.mode.value,
            self.external_reference,
            self.report_version,
            self.revision_sequence,
            self.supersedes_evidence_id,
            None if self.reported_total is None else self.reported_total.to_dict(),
            tuple(item.to_dict() for item in self.reported_components),
            self.effective_at.to_dict(),
        )


__all__ = [name for name in globals() if name.startswith("Only")]
