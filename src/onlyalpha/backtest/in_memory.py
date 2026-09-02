"""Deterministic in-memory Backtest lifecycle adapter for unit/contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .execution import (
    OnlyBacktestAttempt,
    OnlyBacktestAttemptId,
    OnlyBacktestAttemptState,
    OnlyBacktestExecutionClaim,
    OnlyBacktestExecutionPolicy,
    OnlyBacktestWorkerInstanceId,
)
from .model import OnlyBacktestRun, OnlyBacktestRunFailure, OnlyBacktestRunId, OnlyBacktestRunState


class OnlyInMemoryBacktestExecutionStore:
    def __init__(self, runs: tuple[OnlyBacktestRun, ...] = ()) -> None:
        self.runs: dict[OnlyBacktestRunId, OnlyBacktestRun] = {run.run_id: run for run in runs}
        self.attempts: dict[OnlyBacktestAttemptId, OnlyBacktestAttempt] = {}
        self._fencing: dict[OnlyBacktestRunId, int] = {}

    def add(self, run: OnlyBacktestRun) -> None:
        if run.run_id in self.runs:
            raise ValueError("BACKTEST_RUN_ALREADY_EXISTS")
        self.runs[run.run_id] = run

    def claim_next(
        self,
        worker_instance_id: OnlyBacktestWorkerInstanceId,
        attempt_id: OnlyBacktestAttemptId,
        policy: OnlyBacktestExecutionPolicy,
    ) -> OnlyBacktestExecutionClaim | None:
        now = datetime.now(UTC)
        for run in sorted(self.runs.values(), key=lambda item: item.run_id.value):
            if run.state is not OnlyBacktestRunState.QUEUED:
                continue
            number = 1 + max(
                (item.attempt_number for item in self.attempts.values() if item.run_id == run.run_id), default=0
            )
            if number > policy.max_attempts:
                continue
            running = run.transition(OnlyBacktestRunState.RUNNING, at=now)
            self.runs[run.run_id] = running
            token = self._fencing.get(run.run_id, 0) + 1
            self._fencing[run.run_id] = token
            attempt = OnlyBacktestAttempt(
                attempt_id,
                run.run_id,
                number,
                OnlyBacktestAttemptState.ACTIVE,
                worker_instance_id,
                token,
                now,
                now,
                now + policy.lease_duration,
            )
            self.attempts[attempt_id] = attempt
            return OnlyBacktestExecutionClaim(running, attempt)
        return None

    def heartbeat(self, claim: OnlyBacktestExecutionClaim, lease_duration: timedelta) -> OnlyBacktestAttempt:
        current = self.attempts[claim.attempt.attempt_id]
        if current != claim.attempt or current.state is not OnlyBacktestAttemptState.ACTIVE:
            raise RuntimeError("BACKTEST_ATTEMPT_FENCED")
        now = datetime.now(UTC)
        updated = OnlyBacktestAttempt(
            current.attempt_id,
            current.run_id,
            current.attempt_number,
            current.state,
            current.worker_instance_id,
            current.fencing_token,
            current.claimed_at,
            now,
            now + lease_duration,
        )
        self.attempts[current.attempt_id] = updated
        return updated

    def complete(
        self,
        claim: OnlyBacktestExecutionClaim,
        *,
        evidence_fingerprint: str,
        result_fingerprint: str,
        determinism_fingerprint: str,
    ) -> OnlyBacktestRun:
        self._assert_active(claim)
        now = datetime.now(UTC)
        current = self.runs[claim.run.run_id]
        if current.state not in {OnlyBacktestRunState.RUNNING, OnlyBacktestRunState.CANCEL_REQUESTED}:
            raise RuntimeError("BACKTEST_RUN_STATE_CONFLICT")
        updated = current.transition(
            OnlyBacktestRunState.COMPLETED,
            at=now,
            evidence_fingerprint=evidence_fingerprint,
            result_fingerprint=result_fingerprint,
            determinism_fingerprint=determinism_fingerprint,
        )
        self.runs[current.run_id] = updated
        self._finish_attempt(claim, OnlyBacktestAttemptState.SUCCEEDED, now)
        return updated

    def fail(self, claim: OnlyBacktestExecutionClaim, failure: OnlyBacktestRunFailure) -> OnlyBacktestRun:
        self._assert_active(claim)
        now = datetime.now(UTC)
        current = self.runs[claim.run.run_id]
        updated = current.transition(OnlyBacktestRunState.FAILED, at=now, failure=failure)
        self.runs[current.run_id] = updated
        self._finish_attempt(claim, OnlyBacktestAttemptState.FAILED, now, failure)
        return updated

    def cancel(self, claim: OnlyBacktestExecutionClaim) -> OnlyBacktestRun:
        self._assert_active(claim)
        current = self.runs[claim.run.run_id]
        updated = current.transition(OnlyBacktestRunState.CANCELLED, at=datetime.now(UTC))
        self.runs[current.run_id] = updated
        self._finish_attempt(claim, OnlyBacktestAttemptState.CANCELLED, updated.finished_at or datetime.now(UTC))
        return updated

    def _assert_active(self, claim: OnlyBacktestExecutionClaim) -> None:
        current = self.attempts.get(claim.attempt.attempt_id)
        if current != claim.attempt or current is None or current.state is not OnlyBacktestAttemptState.ACTIVE:
            raise RuntimeError("BACKTEST_ATTEMPT_FENCED")

    def _finish_attempt(
        self,
        claim: OnlyBacktestExecutionClaim,
        state: OnlyBacktestAttemptState,
        at: datetime,
        failure: OnlyBacktestRunFailure | None = None,
    ) -> None:
        current = self.attempts[claim.attempt.attempt_id]
        self.attempts[current.attempt_id] = OnlyBacktestAttempt(
            current.attempt_id,
            current.run_id,
            current.attempt_number,
            state,
            current.worker_instance_id,
            current.fencing_token,
            current.claimed_at,
            current.last_heartbeat_at,
            current.lease_expires_at,
            at,
            None if failure is None else failure.code,
            None if failure is None else failure.detail,
        )


__all__ = ["OnlyInMemoryBacktestExecutionStore"]
