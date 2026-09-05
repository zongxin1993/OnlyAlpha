"""Stable Product DTOs for Strategy Freeze, Query and Promotion."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _StrategyDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class StrategyFreezeRequest(_StrategyDto):
    research_run_id: str
    candidate_fingerprint: str
    actor: str
    comment: str | None = None


class StrategyFreezeResponse(_StrategyDto):
    schema_version: Literal[1] = 1
    strategy_fingerprint: str
    disposition: str
    freeze_record_fingerprint: str
    replayed: bool


class QualificationEvidenceReferenceDto(_StrategyDto):
    kind: str
    evidence_fingerprint: str
    locator_fingerprint: str | None = None
    subject_binding_fingerprint: str | None = None


class QualificationEvaluationRequest(_StrategyDto):
    policy_id: str
    policy_version: str
    evidence: list[QualificationEvidenceReferenceDto]


class QualificationDecisionResponse(_StrategyDto):
    schema_version: Literal[1] = 1
    decision: dict[str, object]
    replayed: bool = False


class QualificationPolicyResponse(_StrategyDto):
    schema_version: Literal[1] = 1
    policy: dict[str, object]


class QualificationPolicyListResponse(_StrategyDto):
    schema_version: Literal[1] = 1
    policies: tuple[dict[str, object], ...]


class QualificationDecisionListResponse(_StrategyDto):
    schema_version: Literal[1] = 1
    decisions: tuple[dict[str, object], ...]


class StrategyPromotionRequest(_StrategyDto):
    freeze_relation_fingerprint: str
    reason: str
    actor: str


class QualifiedStrategyPromotionRequest(_StrategyDto):
    to_stage: Literal["BACKTEST", "SIM"]
    qualification_decision_fingerprint: str
    policy_fingerprint: str
    reason: str
    actor: str


class StrategyPromotionResponse(_StrategyDto):
    schema_version: Literal[1] = 1
    strategy_fingerprint: str
    promotion_record_fingerprint: str
    from_stage: str
    to_stage: str
    decision: str
    replayed: bool


class StrategyDto(_StrategyDto):
    schema_version: Literal[1] = 1
    strategy_fingerprint: str
    revision: dict[str, object]
    freeze_relation_fingerprints: tuple[str, ...]
    current_stage: str
    promotion_records: tuple[dict[str, object], ...]


__all__ = [name for name in globals() if name.startswith("Strategy")]
