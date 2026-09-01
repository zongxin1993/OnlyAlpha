"""Deterministic Trade-based execution reference planning."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.data.enums import OnlyMarketDataQualityFlag
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.market_data.realtime_state import (
    OnlyRealtimeMarketSnapshot,
    OnlyRealtimeMarketStateStore,
    OnlyRealtimeTradeReference,
)
from onlyalpha.risk.enums import OnlyOrderRiskChange


class OnlyExecutionReferenceKind(StrEnum):
    LAST_TRADE = "LAST_TRADE"


class OnlyExecutionReferenceFallback(StrEnum):
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class OnlyExecutionReferenceProfile(OnlyDomainModel):
    """Versioned Execution Profile fragment; never Strategy identity."""

    profile_id: str
    policy_version: int
    reference_kind: OnlyExecutionReferenceKind
    fallback: OnlyExecutionReferenceFallback
    max_age_ns: int
    required_source_id: str | None = None
    maximum_deviation_rate: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or self.policy_version < 1 or self.max_age_ns <= 0:
            raise ValueError("EXECUTION_REFERENCE_PROFILE_INVALID")
        if self.fallback is not OnlyExecutionReferenceFallback.NONE:
            raise ValueError("EXECUTION_REFERENCE_FALLBACK_UNSUPPORTED")
        if self.maximum_deviation_rate is not None and not (Decimal(0) <= self.maximum_deviation_rate <= 1):
            raise ValueError("EXECUTION_REFERENCE_DEVIATION_INVALID")

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class OnlyExecutionReferenceEvidence(OnlyDomainModel):
    snapshot_fingerprint: str
    profile_fingerprint: str
    reference_kind: OnlyExecutionReferenceKind
    market_update_id: str
    source_id: str
    instrument_id: str
    data_version: str
    source_sequence: int
    event_time_ns: int
    observed_time_ns: int
    quality_flags: tuple[str, ...]
    trade_id: str
    reference_price: OnlyPrice
    proposal_price: OnlyPrice | None
    resolved_order_price: OnlyPrice


@dataclass(frozen=True, slots=True)
class OnlyExecutionReferencePlanningResult:
    accepted: bool
    snapshot: OnlyRealtimeMarketSnapshot
    evidence: OnlyExecutionReferenceEvidence | None = None
    failure_code: str | None = None
    message: str | None = None


class OnlyExecutionReferencePlanningService:
    """Captures once, performs reference Risk admission, then resolves pricing."""

    _invalid_quality = frozenset(
        {
            OnlyMarketDataQualityFlag.STALE,
            OnlyMarketDataQualityFlag.DUPLICATE,
            OnlyMarketDataQualityFlag.OUT_OF_ORDER,
            OnlyMarketDataQualityFlag.UNEXPECTED_GAP,
            OnlyMarketDataQualityFlag.SOURCE_CONFLICT,
            OnlyMarketDataQualityFlag.NON_DETERMINISTIC_SOURCE,
            OnlyMarketDataQualityFlag.PARTIAL,
        }
    )

    def __init__(
        self,
        state: OnlyRealtimeMarketStateStore,
        profile: OnlyExecutionReferenceProfile,
    ) -> None:
        self._state = state
        self.profile = profile

    def plan(
        self,
        request: OnlyOrderRequest,
        risk_change: OnlyOrderRiskChange,
        captured_at: OnlyTimestamp,
    ) -> OnlyExecutionReferencePlanningResult:
        snapshot = self._state.capture(captured_at)
        if risk_change in {OnlyOrderRiskChange.RISK_REDUCING, OnlyOrderRiskChange.RISK_NEUTRAL}:
            return OnlyExecutionReferencePlanningResult(True, snapshot)
        reference = snapshot.latest_trade(request.instrument_id)
        if reference is None:
            return self._reject(snapshot, "REFERENCE_UNAVAILABLE", "trusted Trade reference is unavailable")
        failure = self._validate_reference(snapshot, reference, captured_at)
        if failure is not None:
            return failure
        reference_price = reference.trade.price
        resolved = request.price if request.order_type is OnlyOrderType.LIMIT else reference_price
        if resolved is None:
            return self._reject(snapshot, "REFERENCE_UNAVAILABLE", "execution price cannot be resolved")
        maximum = self.profile.maximum_deviation_rate
        if maximum is not None and request.price is not None:
            deviation = abs(request.price.value - reference_price.value) / reference_price.value
            if deviation > maximum:
                return self._reject(
                    snapshot,
                    "ORDER_PRICE_DEVIATION_EXCEEDED",
                    "proposed order price exceeds the Execution Profile deviation limit",
                )
        evidence = OnlyExecutionReferenceEvidence(
            snapshot.fingerprint,
            self.profile.fingerprint,
            self.profile.reference_kind,
            str(reference.update_id),
            str(reference.source_id),
            str(reference.instrument_id),
            str(reference.data_version),
            reference.source_sequence,
            reference.ts_event.unix_nanos,
            reference.ts_init.unix_nanos,
            tuple(sorted(item.value for item in reference.quality.flags)),
            str(reference.trade.trade_id),
            reference_price,
            request.price,
            resolved,
        )
        return OnlyExecutionReferencePlanningResult(True, snapshot, evidence)

    def _validate_reference(
        self,
        snapshot: OnlyRealtimeMarketSnapshot,
        reference: OnlyRealtimeTradeReference,
        captured_at: OnlyTimestamp,
    ) -> OnlyExecutionReferencePlanningResult | None:
        required_source = self.profile.required_source_id
        if required_source is not None and str(reference.source_id) != required_source:
            return self._reject(snapshot, "REFERENCE_SOURCE_MISMATCH", "Trade reference source is not admitted")
        if snapshot.has_unresolved_gap(reference):
            return self._reject(snapshot, "REFERENCE_GAP_UNRESOLVED", "Trade reference continuity is unresolved")
        if self._invalid_quality.intersection(reference.quality.flags):
            return self._reject(snapshot, "REFERENCE_QUALITY_INVALID", "Trade reference quality is not admitted")
        if (
            reference.ts_init.unix_nanos > captured_at.unix_nanos
            or reference.ts_event.unix_nanos > captured_at.unix_nanos
        ):
            return self._reject(snapshot, "REFERENCE_TIME_INVALID", "Trade reference is later than snapshot capture")
        age = captured_at.unix_nanos - reference.ts_event.unix_nanos
        if age > self.profile.max_age_ns:
            return self._reject(snapshot, "REFERENCE_STALE", "Trade reference exceeds the Execution Profile age limit")
        return None

    @staticmethod
    def _reject(
        snapshot: OnlyRealtimeMarketSnapshot,
        code: str,
        message: str,
    ) -> OnlyExecutionReferencePlanningResult:
        return OnlyExecutionReferencePlanningResult(False, snapshot, None, code, message)


__all__ = [name for name in globals() if name.startswith("Only")]
