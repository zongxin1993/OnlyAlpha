"""Deterministic in-memory Backtest lifecycle adapter for unit/contract tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from .errors import OnlyBacktestNotFoundError
from .execution import (
    OnlyBacktestAttempt,
    OnlyBacktestAttemptId,
    OnlyBacktestAttemptState,
    OnlyBacktestExecutionClaim,
    OnlyBacktestExecutionPolicy,
    OnlyBacktestWorkerInstanceId,
)
from .model import (
    OnlyBacktestRun,
    OnlyBacktestRunFailure,
    OnlyBacktestRunFailurePhase,
    OnlyBacktestRunId,
    OnlyBacktestRunState,
)


class OnlyInMemoryBacktestExecutionStore:
    def __init__(
        self,
        runs: tuple[OnlyBacktestRun, ...] = (),
        *,
        now_utc: Callable[[], datetime],
    ) -> None:
        self.runs: dict[OnlyBacktestRunId, OnlyBacktestRun] = {run.run_id: run for run in runs}
        self.attempts: dict[OnlyBacktestAttemptId, OnlyBacktestAttempt] = {}
        self._fencing: dict[OnlyBacktestRunId, int] = {}
        self._now_utc = now_utc

    def add(self, run: OnlyBacktestRun) -> None:
        if run.run_id in self.runs:
            raise ValueError("BACKTEST_RUN_ALREADY_EXISTS")
        self.runs[run.run_id] = run

    def load(self, run_id: OnlyBacktestRunId) -> OnlyBacktestRun:
        try:
            return self.runs[run_id]
        except KeyError as exc:
            raise OnlyBacktestNotFoundError(run_id.value) from exc

    def claim_next(
        self,
        worker_instance_id: OnlyBacktestWorkerInstanceId,
        attempt_id: OnlyBacktestAttemptId,
        policy: OnlyBacktestExecutionPolicy,
        eligible_run_ids: tuple[str, ...] | None = None,
    ) -> OnlyBacktestExecutionClaim | None:
        now = self._now_utc()
        for run in sorted(self.runs.values(), key=lambda item: item.run_id.value):
            if eligible_run_ids is not None and run.run_id.value not in eligible_run_ids:
                continue
            if run.state not in {OnlyBacktestRunState.QUEUED, OnlyBacktestRunState.RUNNING}:
                continue
            if any(item.run_id == run.run_id and item.state is item.state.ACTIVE for item in self.attempts.values()):
                continue
            number = 1 + max(
                (item.attempt_number for item in self.attempts.values() if item.run_id == run.run_id), default=0
            )
            if number > policy.max_attempts:
                continue
            running = (
                run
                if run.state is OnlyBacktestRunState.RUNNING
                else run.transition(OnlyBacktestRunState.RUNNING, at=now)
            )
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
        current = self._active_attempt(claim)
        now = self._now_utc()
        if current.lease_expires_at <= now:
            raise RuntimeError("BACKTEST_ATTEMPT_FENCED")
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

    def load_attempt(self, attempt_id: OnlyBacktestAttemptId) -> OnlyBacktestAttempt:
        try:
            return self.attempts[attempt_id]
        except KeyError as exc:
            raise RuntimeError("BACKTEST_ATTEMPT_NOT_FOUND") from exc

    def expire_next(
        self,
        policy: OnlyBacktestExecutionPolicy,
        eligible_run_ids: tuple[str, ...] | None = None,
    ) -> OnlyBacktestAttempt | None:
        now = self._now_utc()
        eligible = None if eligible_run_ids is None else set(eligible_run_ids)
        candidates = sorted(
            (
                item
                for item in self.attempts.values()
                if item.state is item.state.ACTIVE
                and item.lease_expires_at <= now
                and (eligible is None or item.run_id.value in eligible)
            ),
            key=lambda item: (item.lease_expires_at, item.attempt_id.value),
        )
        if not candidates:
            return None
        current = candidates[0]
        expired = OnlyBacktestAttempt(
            current.attempt_id,
            current.run_id,
            current.attempt_number,
            OnlyBacktestAttemptState.EXPIRED,
            current.worker_instance_id,
            current.fencing_token,
            current.claimed_at,
            current.last_heartbeat_at,
            current.lease_expires_at,
            now,
            "LEASE_EXPIRED",
            "Backtest Attempt lease expired",
        )
        self.attempts[current.attempt_id] = expired
        run = self.runs[current.run_id]
        if current.attempt_number >= policy.max_attempts and run.state is OnlyBacktestRunState.RUNNING:
            failure = OnlyBacktestRunFailure(
                phase=OnlyBacktestRunFailurePhase.OPERATIONAL,
                code="ATTEMPT_LIMIT_EXHAUSTED",
                detail="Backtest retry budget was exhausted",
            )
            self.runs[run.run_id] = run.transition(OnlyBacktestRunState.FAILED, at=now, failure=failure)
        return expired

    def load_reconciliation_candidate(
        self,
        eligible_run_ids: tuple[str, ...] | None = None,
    ) -> OnlyBacktestRun | None:
        eligible = None if eligible_run_ids is None else set(eligible_run_ids)
        candidates = tuple(
            run
            for run in self.runs.values()
            if run.state in {OnlyBacktestRunState.RUNNING, OnlyBacktestRunState.CANCEL_REQUESTED}
            and (eligible is None or run.run_id.value in eligible)
            and not any(
                attempt.run_id == run.run_id and attempt.state is attempt.state.ACTIVE
                for attempt in self.attempts.values()
            )
        )
        return None if not candidates else sorted(candidates, key=lambda item: (item.queued_at, item.run_id.value))[0]

    def reconcile_complete(
        self,
        run: OnlyBacktestRun,
        *,
        evidence_fingerprint: str,
        result_fingerprint: str,
        determinism_fingerprint: str,
    ) -> OnlyBacktestRun:
        return self._reconcile(
            run,
            OnlyBacktestRunState.COMPLETED,
            evidence_fingerprint=evidence_fingerprint,
            result_fingerprint=result_fingerprint,
            determinism_fingerprint=determinism_fingerprint,
        )

    def reconcile_fail(self, run: OnlyBacktestRun, failure: OnlyBacktestRunFailure) -> OnlyBacktestRun:
        return self._reconcile(run, OnlyBacktestRunState.FAILED, failure=failure)

    def reconcile_cancel(self, run: OnlyBacktestRun) -> OnlyBacktestRun:
        if run.state is not OnlyBacktestRunState.CANCEL_REQUESTED:
            raise RuntimeError("BACKTEST_CANCELLATION_NOT_REQUESTED")
        return self._reconcile(run, OnlyBacktestRunState.CANCELLED)

    def _reconcile(
        self,
        expected: OnlyBacktestRun,
        target: OnlyBacktestRunState,
        *,
        evidence_fingerprint: str | None = None,
        result_fingerprint: str | None = None,
        determinism_fingerprint: str | None = None,
        failure: OnlyBacktestRunFailure | None = None,
    ) -> OnlyBacktestRun:
        current = self.runs[expected.run_id]
        if current != expected or any(
            attempt.run_id == current.run_id and attempt.state is attempt.state.ACTIVE
            for attempt in self.attempts.values()
        ):
            raise RuntimeError("BACKTEST_RECONCILIATION_CONFLICT")
        updated = current.transition(
            target,
            at=self._now_utc(),
            evidence_fingerprint=evidence_fingerprint,
            result_fingerprint=result_fingerprint,
            determinism_fingerprint=determinism_fingerprint,
            failure=failure,
        )
        self.runs[current.run_id] = updated
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
        now = self._now_utc()
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

    def fail(
        self,
        claim: OnlyBacktestExecutionClaim,
        failure: OnlyBacktestRunFailure,
        policy: OnlyBacktestExecutionPolicy,
    ) -> OnlyBacktestRun:
        self._assert_active(claim)
        now = self._now_utc()
        current = self.runs[claim.run.run_id]
        if failure.code in policy.retryable_failure_codes and claim.attempt.attempt_number < policy.max_attempts:
            updated = current
        else:
            updated = current.transition(OnlyBacktestRunState.FAILED, at=now, failure=failure)
        self.runs[current.run_id] = updated
        self._finish_attempt(claim, OnlyBacktestAttemptState.FAILED, now, failure)
        return updated

    def cancel(self, claim: OnlyBacktestExecutionClaim) -> OnlyBacktestRun:
        self._assert_active(claim)
        current = self.runs[claim.run.run_id]
        if current.state is not OnlyBacktestRunState.CANCEL_REQUESTED:
            raise RuntimeError("BACKTEST_CANCELLATION_NOT_REQUESTED")
        updated = current.transition(OnlyBacktestRunState.CANCELLED, at=self._now_utc())
        self.runs[current.run_id] = updated
        self._finish_attempt(claim, OnlyBacktestAttemptState.CANCELLED, updated.finished_at or self._now_utc())
        return updated

    def _assert_active(self, claim: OnlyBacktestExecutionClaim) -> None:
        current = self._active_attempt(claim)
        if current.lease_expires_at <= self._now_utc():
            raise RuntimeError("BACKTEST_ATTEMPT_FENCED")

    def _active_attempt(self, claim: OnlyBacktestExecutionClaim) -> OnlyBacktestAttempt:
        current = self.attempts.get(claim.attempt.attempt_id)
        if (
            current is None
            or current.state is not OnlyBacktestAttemptState.ACTIVE
            or current.run_id != claim.run.run_id
            or current.attempt_number != claim.attempt.attempt_number
            or current.worker_instance_id != claim.attempt.worker_instance_id
            or current.fencing_token != claim.attempt.fencing_token
        ):
            raise RuntimeError("BACKTEST_ATTEMPT_FENCED")
        return current

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
