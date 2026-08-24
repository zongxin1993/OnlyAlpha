"""Append-only Strategy promotion evidence and derived stage projection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.strategy.errors import OnlyStrategyPromotionError
from onlyalpha.strategy.store import OnlyStrategyRevisionStore


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
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
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
        if include_fingerprint:
            payload["record_fingerprint"] = self.record_fingerprint
        return payload


class OnlyStrategyPromotionLedger(Protocol):
    def records(self, strategy_fingerprint: str) -> tuple[OnlyStrategyPromotionRecord, ...]: ...

    def append(self, record: OnlyStrategyPromotionRecord) -> OnlyStrategyPromotionRecord: ...


class OnlyStrategyPromotionService:
    def __init__(
        self,
        strategies: OnlyStrategyRevisionStore,
        ledger: OnlyStrategyPromotionLedger,
        audit_time: Callable[[], datetime],
    ) -> None:
        self._strategies = strategies
        self._ledger = ledger
        self._audit_time = audit_time

    def current_stage(self, strategy_fingerprint: str) -> OnlyStrategyPromotionStage:
        if not self._strategies.exists(strategy_fingerprint):
            raise OnlyStrategyPromotionError("STRATEGY_NOT_FOUND", strategy_fingerprint)
        stage = OnlyStrategyPromotionStage.RESEARCH
        previous: str | None = None
        for record in self._ledger.records(strategy_fingerprint):
            if record.strategy_fingerprint != strategy_fingerprint or record.previous_record_fingerprint != previous:
                raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", strategy_fingerprint)
            if record.record_fingerprint != only_canonical_fingerprint(record.to_dict(include_fingerprint=False)):
                raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", record.record_fingerprint)
            if record.from_stage is not stage or _NEXT.get(stage) is not record.to_stage:
                raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", "stage chain is invalid")
            if record.decision is OnlyStrategyPromotionDecision.APPROVED:
                stage = record.to_stage
            previous = record.record_fingerprint
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
    ) -> OnlyStrategyPromotionRecord:
        current = self.current_stage(strategy_fingerprint)
        if _NEXT.get(current) is not to_stage:
            raise OnlyStrategyPromotionError(
                "ILLEGAL_PROMOTION_TRANSITION",
                f"{current.value} -> {to_stage.value}",
            )
        records = self._ledger.records(strategy_fingerprint)
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
        expected = None if not values else values[-1].record_fingerprint
        if record.previous_record_fingerprint != expected:
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CONFLICT", record.strategy_fingerprint)
        values.append(record)
        return record


def _sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


def _utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")


__all__ = [name for name in globals() if name.startswith("Only")]
