"""Immutable Risk decisions, rejections and error details."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderRequestId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.risk.enums import (
    OnlyRiskOutcome,
    OnlyRiskRejectionCode,
    OnlyRiskRuleScope,
    OnlyRiskSeverity,
)
from onlyalpha.risk.identifiers import OnlyRiskRuleId


def _freeze_details(details: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(details))


@dataclass(frozen=True, slots=True)
class OnlyRiskRejection(OnlyDomainModel):
    rule_id: OnlyRiskRuleId
    code: OnlyRiskRejectionCode
    message: str
    scope: OnlyRiskRuleScope
    severity: OnlyRiskSeverity = OnlyRiskSeverity.ERROR
    retryable: bool = False
    details: Mapping[str, str] = field(default_factory=dict)
    requested_value: str | None = None
    allowed_value: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _freeze_details(self.details))


@dataclass(frozen=True, slots=True)
class OnlyRiskErrorInfo(OnlyDomainModel):
    rule_id: OnlyRiskRuleId
    scope: OnlyRiskRuleScope
    exception_type: str
    message: str
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    request_id: OnlyOrderRequestId
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    retryable: bool = False
    details: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _freeze_details(self.details))


@dataclass(frozen=True, slots=True)
class OnlyRiskObservation(OnlyDomainModel):
    rule_id: OnlyRiskRuleId
    code: OnlyRiskRejectionCode
    message: str
    scope: OnlyRiskRuleScope
    details: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _freeze_details(self.details))


@dataclass(frozen=True, slots=True)
class OnlyRiskDecision(OnlyDomainModel):
    outcome: OnlyRiskOutcome
    evaluated_rule_ids: tuple[OnlyRiskRuleId, ...] = ()
    rejection: OnlyRiskRejection | None = None
    error: OnlyRiskErrorInfo | None = None
    observations: tuple[OnlyRiskObservation, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome is OnlyRiskOutcome.REJECT and self.rejection is None:
            raise ValueError("REJECT decision requires rejection")
        if self.outcome is OnlyRiskOutcome.ERROR and self.error is None:
            raise ValueError("ERROR decision requires error")
        if self.outcome is OnlyRiskOutcome.ACCEPT and (self.rejection is not None or self.error is not None):
            raise ValueError("ACCEPT decision cannot contain rejection or error")

    @property
    def is_accepted(self) -> bool:
        return self.outcome is OnlyRiskOutcome.ACCEPT

    @property
    def is_rejected(self) -> bool:
        return self.outcome is OnlyRiskOutcome.REJECT

    @property
    def is_error(self) -> bool:
        return self.outcome is OnlyRiskOutcome.ERROR

    @classmethod
    def accepted(
        cls,
        evaluated_rule_ids: tuple[OnlyRiskRuleId, ...] = (),
        observations: tuple[OnlyRiskObservation, ...] = (),
    ) -> OnlyRiskDecision:
        return cls(OnlyRiskOutcome.ACCEPT, evaluated_rule_ids, observations=observations)

    @classmethod
    def rejected(
        cls,
        rejection: OnlyRiskRejection,
        evaluated_rule_ids: tuple[OnlyRiskRuleId, ...] = (),
        observations: tuple[OnlyRiskObservation, ...] = (),
    ) -> OnlyRiskDecision:
        return cls(OnlyRiskOutcome.REJECT, evaluated_rule_ids, rejection, observations=observations)

    @classmethod
    def failed(
        cls,
        error: OnlyRiskErrorInfo,
        evaluated_rule_ids: tuple[OnlyRiskRuleId, ...] = (),
        observations: tuple[OnlyRiskObservation, ...] = (),
    ) -> OnlyRiskDecision:
        return cls(OnlyRiskOutcome.ERROR, evaluated_rule_ids, error=error, observations=observations)
