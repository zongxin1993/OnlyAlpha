"""Append-only Strategy promotion evidence and derived stage projection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.strategy.errors import OnlyStrategyPromotionError
from onlyalpha.strategy.store import OnlyStrategyRevisionReader


class OnlyStrategyPromotionStage(StrEnum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    SIM = "SIM"
    LIVE_ELIGIBLE = "LIVE_ELIGIBLE"


class OnlyStrategyPromotionDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


_NEXT = {
    OnlyStrategyPromotionStage.RESEARCH: OnlyStrategyPromotionStage.BACKTEST,
    OnlyStrategyPromotionStage.BACKTEST: OnlyStrategyPromotionStage.SIM,
    OnlyStrategyPromotionStage.SIM: OnlyStrategyPromotionStage.LIVE_ELIGIBLE,
}


@dataclass(frozen=True, slots=True)
class _OnlyQualifiedPromotionAuthorization:
    qualification_decision_fingerprint: str
    seal: object


_QUALIFIED_PROMOTION_SEAL = object()


def _only_authorize_qualified_promotion(
    qualification_decision_fingerprint: str,
) -> _OnlyQualifiedPromotionAuthorization:
    _sha(qualification_decision_fingerprint, "Qualification Decision identity")
    return _OnlyQualifiedPromotionAuthorization(qualification_decision_fingerprint, _QUALIFIED_PROMOTION_SEAL)


def _only_require_qualified_promotion(
    authorization: _OnlyQualifiedPromotionAuthorization,
) -> str:
    if (
        not isinstance(authorization, _OnlyQualifiedPromotionAuthorization)
        or authorization.seal is not _QUALIFIED_PROMOTION_SEAL
    ):
        raise OnlyStrategyPromotionError(
            "QUALIFICATION_DECISION_NOT_APPROVED",
            "Promotion requires verified Qualification authorization",
        )
    return authorization.qualification_decision_fingerprint


@dataclass(frozen=True, slots=True)
class OnlyStrategyPromotionRecord:
    strategy_fingerprint: str
    from_stage: OnlyStrategyPromotionStage
    to_stage: OnlyStrategyPromotionStage
    evidence_fingerprints: tuple[str, ...]
    decision: OnlyStrategyPromotionDecision
    reason: str
    actor: str
    recorded_at: datetime
    previous_record_fingerprint: str | None = None
    qualification_decision_fingerprint: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version not in {1, 2}:
            raise ValueError("unsupported Strategy Promotion Record schema")
        _sha(self.strategy_fingerprint, "strategy_fingerprint")
        if _NEXT.get(self.from_stage) is not self.to_stage:
            raise ValueError("ILLEGAL_PROMOTION_TRANSITION")
        canonical = tuple(sorted(self.evidence_fingerprints))
        if not canonical or canonical != self.evidence_fingerprints or len(canonical) != len(set(canonical)):
            raise ValueError("Promotion evidence must be canonical, non-empty and unique")
        for value in canonical:
            _sha(value, "Promotion evidence")
        if not self.reason.strip() or not self.actor.strip():
            raise ValueError("Promotion reason and actor are required")
        _utc(self.recorded_at, "Promotion recorded_at")
        if self.previous_record_fingerprint is not None:
            _sha(self.previous_record_fingerprint, "previous Promotion Record identity")
        if self.schema_version == 1:
            if self.qualification_decision_fingerprint is not None:
                raise ValueError("legacy Promotion Record cannot claim Qualification evidence")
        elif self.qualification_decision_fingerprint is None:
            raise ValueError("Qualification Decision is required for a new Promotion Record")
        else:
            _sha(self.qualification_decision_fingerprint, "Qualification Decision identity")
            if self.qualification_decision_fingerprint not in self.evidence_fingerprints:
                raise ValueError("Qualification Decision must be Promotion evidence")

    @property
    def record_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "strategy_fingerprint": self.strategy_fingerprint,
            "from_stage": self.from_stage.value,
            "to_stage": self.to_stage.value,
            "evidence_fingerprints": list(self.evidence_fingerprints),
            "decision": self.decision.value,
            "reason": self.reason,
            "actor": self.actor,
            "recorded_at": self.recorded_at.isoformat(),
            "previous_record_fingerprint": self.previous_record_fingerprint,
        }
        if self.schema_version == 2:
            payload["qualification_decision_fingerprint"] = self.qualification_decision_fingerprint
        if include_fingerprint:
            payload["record_fingerprint"] = self.record_fingerprint
        return payload


class OnlyStrategyPromotionLedger(Protocol):
    def records(self, strategy_fingerprint: str) -> tuple[OnlyStrategyPromotionRecord, ...]: ...

    def append(self, record: OnlyStrategyPromotionRecord) -> OnlyStrategyPromotionRecord: ...


class OnlyStrategyPromotionService:
    def __init__(
        self,
        strategies: OnlyStrategyRevisionReader,
        ledger: OnlyStrategyPromotionLedger,
        audit_time: Callable[[], datetime],
    ) -> None:
        self._strategies = strategies
        self._ledger = ledger
        self._audit_time = audit_time

    def current_stage(self, strategy_fingerprint: str) -> OnlyStrategyPromotionStage:
        try:
            self._strategies.load_verified(strategy_fingerprint)
        except Exception as exc:
            code = getattr(exc, "code", "STRATEGY_NOT_FOUND")
            raise OnlyStrategyPromotionError(str(code), strategy_fingerprint) from exc
        stage = OnlyStrategyPromotionStage.RESEARCH
        for record in only_verified_strategy_promotion_chain(
            self._ledger.records(strategy_fingerprint),
            strategy_fingerprint,
        ):
            if record.from_stage is not stage or _NEXT.get(stage) is not record.to_stage:
                raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", "stage chain is invalid")
            if record.decision is OnlyStrategyPromotionDecision.APPROVED:
                stage = record.to_stage
        return stage

    def record(
        self,
        *,
        strategy_fingerprint: str,
        to_stage: OnlyStrategyPromotionStage,
        evidence_fingerprints: tuple[str, ...],
        decision: OnlyStrategyPromotionDecision,
        reason: str,
        actor: str,
        qualification_authorization: _OnlyQualifiedPromotionAuthorization,
    ) -> OnlyStrategyPromotionRecord:
        qualification_decision_fingerprint = _only_require_qualified_promotion(qualification_authorization)
        current = self.current_stage(strategy_fingerprint)
        if _NEXT.get(current) is not to_stage:
            raise OnlyStrategyPromotionError(
                "ILLEGAL_PROMOTION_TRANSITION",
                f"{current.value} -> {to_stage.value}",
            )
        records = only_verified_strategy_promotion_chain(
            self._ledger.records(strategy_fingerprint),
            strategy_fingerprint,
        )
        timestamp = self._audit_time()
        _utc(timestamp, "Promotion audit time")
        try:
            record = OnlyStrategyPromotionRecord(
                strategy_fingerprint,
                current,
                to_stage,
                tuple(sorted(evidence_fingerprints)),
                decision,
                reason,
                actor,
                timestamp,
                None if not records else records[-1].record_fingerprint,
                qualification_decision_fingerprint,
                2,
            )
        except ValueError as exc:
            code = "ILLEGAL_PROMOTION_TRANSITION" if "ILLEGAL" in str(exc) else "PROMOTION_RECORD_INVALID"
            raise OnlyStrategyPromotionError(code, str(exc)) from exc
        return self._ledger.append(record)


class OnlyInMemoryStrategyPromotionLedger(OnlyStrategyPromotionLedger):
    def __init__(self) -> None:
        self._records: dict[str, list[OnlyStrategyPromotionRecord]] = {}

    def records(self, strategy_fingerprint: str) -> tuple[OnlyStrategyPromotionRecord, ...]:
        return tuple(self._records.get(strategy_fingerprint, ()))

    def append(self, record: OnlyStrategyPromotionRecord) -> OnlyStrategyPromotionRecord:
        values = self._records.setdefault(record.strategy_fingerprint, [])
        if any(item.record_fingerprint == record.record_fingerprint for item in values):
            return next(item for item in values if item.record_fingerprint == record.record_fingerprint)
        chain = only_verified_strategy_promotion_chain(tuple(values), record.strategy_fingerprint)
        expected = None if not chain else chain[-1].record_fingerprint
        if record.previous_record_fingerprint != expected:
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CONFLICT", record.strategy_fingerprint)
        values.append(record)
        return record


def only_verified_strategy_promotion_chain(
    records: tuple[OnlyStrategyPromotionRecord, ...],
    strategy_fingerprint: str,
) -> tuple[OnlyStrategyPromotionRecord, ...]:
    """Reconstruct one exact immutable chain without consulting audit timestamps."""

    if not records:
        return ()
    by_fingerprint: dict[str, OnlyStrategyPromotionRecord] = {}
    children: dict[str | None, list[OnlyStrategyPromotionRecord]] = {}
    for record in records:
        if record.strategy_fingerprint != strategy_fingerprint:
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", "Strategy identity differs")
        fingerprint = record.record_fingerprint
        if fingerprint != only_canonical_fingerprint(record.to_dict(include_fingerprint=False)):
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", fingerprint)
        if fingerprint in by_fingerprint:
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", "duplicate Promotion Record")
        by_fingerprint[fingerprint] = record
        children.setdefault(record.previous_record_fingerprint, []).append(record)
    heads = children.get(None, [])
    if len(heads) != 1:
        raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", "Promotion chain must have one head")
    if any(len(values) != 1 for previous, values in children.items() if previous is not None):
        raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", "Promotion chain branches")
    chain: list[OnlyStrategyPromotionRecord] = []
    consumed: set[str] = set()
    current = heads[0]
    while True:
        fingerprint = current.record_fingerprint
        if fingerprint in consumed:
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", "Promotion chain contains a cycle")
        consumed.add(fingerprint)
        chain.append(current)
        next_values = children.get(fingerprint, [])
        if not next_values:
            break
        current = next_values[0]
    if consumed != set(by_fingerprint):
        raise OnlyStrategyPromotionError(
            "PROMOTION_LEDGER_CORRUPT", "Promotion chain contains orphan or cyclic records"
        )
    stage = OnlyStrategyPromotionStage.RESEARCH
    for record in chain:
        if record.from_stage is not stage or _NEXT.get(stage) is not record.to_stage:
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", "stage chain is invalid")
        if record.decision is OnlyStrategyPromotionDecision.APPROVED:
            stage = record.to_stage
    return tuple(chain)


def _sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


def _utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")


__all__ = [name for name in globals() if name.startswith("Only")]
