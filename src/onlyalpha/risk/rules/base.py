"""Uniform Risk Rule abstraction and helpers."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.decisions import OnlyRiskDecision, OnlyRiskRejection
from onlyalpha.risk.enums import (
    OnlyRiskRejectionCode,
    OnlyRiskRuleMode,
    OnlyRiskRuleScope,
    OnlyRiskSeverity,
)
from onlyalpha.risk.identifiers import OnlyRiskRuleId


@dataclass(frozen=True, slots=True)
class OnlyRiskRuleMetadata:
    rule_id: OnlyRiskRuleId
    scope: OnlyRiskRuleScope
    mode: OnlyRiskRuleMode = OnlyRiskRuleMode.ENFORCING
    order: int = 100
    mandatory: bool = False
    description: str = ""
    config: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))
        if self.mandatory and self.mode is not OnlyRiskRuleMode.ENFORCING:
            raise ValueError("Mandatory Risk Rule must be ENFORCING")


class OnlyRiskRule(ABC):
    """A side-effect-free pre-trade rule with a structured decision."""

    def __init__(self, metadata: OnlyRiskRuleMetadata) -> None:
        self._metadata = metadata

    @property
    def metadata(self) -> OnlyRiskRuleMetadata:
        return self._metadata

    @property
    def rule_id(self) -> OnlyRiskRuleId:
        return self._metadata.rule_id

    @property
    def scope(self) -> OnlyRiskRuleScope:
        return self._metadata.scope

    @property
    def mode(self) -> OnlyRiskRuleMode:
        return self._metadata.mode

    @abstractmethod
    def evaluate(
        self,
        request: OnlyOrderRequest,
        context: OnlyRiskEvaluationContext,
    ) -> OnlyRiskDecision: ...

    def _accept(self) -> OnlyRiskDecision:
        return OnlyRiskDecision.accepted()

    def _reject(
        self,
        code: OnlyRiskRejectionCode,
        message: str,
        *,
        requested_value: str | None = None,
        allowed_value: str | None = None,
        retryable: bool = False,
        severity: OnlyRiskSeverity = OnlyRiskSeverity.ERROR,
        details: Mapping[str, str] | None = None,
    ) -> OnlyRiskDecision:
        return OnlyRiskDecision.rejected(
            OnlyRiskRejection(
                self.rule_id,
                code,
                message,
                self.scope,
                severity,
                retryable,
                details or {},
                requested_value,
                allowed_value,
            )
        )
