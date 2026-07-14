"""Immutable audit records for intents which may never become Orders."""

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.risk.decisions import OnlyRiskDecision
from onlyalpha.risk.identifiers import OnlyRiskAuditId


@dataclass(frozen=True, slots=True)
class OnlyOrderIntentAudit(OnlyDomainModel):
    audit_id: OnlyRiskAuditId
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    request: OnlyOrderRequest
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    correlation_id: str


@dataclass(frozen=True, slots=True)
class OnlyRiskDecisionAudit(OnlyDomainModel):
    intent: OnlyOrderIntentAudit
    decision: OnlyRiskDecision
