"""Immutable diagnostics for one in-flight Streaming recovery cycle."""

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.time import OnlyTimestamp

from .phase import OnlyStreamingPhase


class OnlyStreamingRecoveryStage(StrEnum):
    """Diagnostic progress only; phase and continuity remain the control authorities."""

    IDLE = "IDLE"
    PLAN_INSTALLED = "PLAN_INSTALLED"
    LOADING_HISTORY = "LOADING_HISTORY"
    REPLAYING_HISTORY = "REPLAYING_HISTORY"
    RECONCILING_SUFFIX = "RECONCILING_SUFFIX"
    VERIFYING_CONTINUITY = "VERIFYING_CONTINUITY"
    CONTINUITY_VERIFIED = "CONTINUITY_VERIFIED"
    FAILED = "FAILED"
    STOP_CUTOFF = "STOP_CUTOFF"


@dataclass(frozen=True, slots=True)
class OnlyStreamingRecoveryDiagnostics:
    """Read-only projection assembled from existing Streaming authorities."""

    phase: OnlyStreamingPhase
    phase_revision: int
    recovery_generation: int
    recovery_stage: OnlyStreamingRecoveryStage
    recovery_plan_present: bool
    recovery_reason: str | None
    recovery_from: OnlyTimestamp | None
    recovery_to: OnlyTimestamp | None
    processing_lane_revoked: bool | None
    processing_lane_busy: bool
    worker_alive: bool
    worker_failure: str | None
    source_connected: bool
    subscription_active: bool
    last_closed_bar_end: OnlyTimestamp | None
    buffered_suffix_count: int
    pending_live_bar_count: int
    recovery_failure: str | None
    watchdog_seconds: float
