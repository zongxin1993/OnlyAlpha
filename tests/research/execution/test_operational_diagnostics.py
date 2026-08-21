from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.execution.model import (
    OnlyResearchRunAttempt,
    OnlyResearchRunAttemptId,
    OnlyResearchRunAttemptState,
    OnlyResearchWorkerInstanceId,
)
from onlyalpha.research.operations.diagnostics import (
    OnlyResearchDiagnosticPolicy,
    OnlyResearchOperationalDiagnosticService,
)
from onlyalpha.research.operations.logging import only_log_research_operational_event
from onlyalpha.research.operations.model import (
    OnlyResearchOperationalDiagnosisCode,
    OnlyResearchOperationalSnapshot,
    OnlyResearchRunOperationalRecord,
    OnlyResearchWorkerPresence,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunId,
    OnlyResearchRunState,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.research.specification.support import registry, specification

NOW = datetime(2026, 8, 21, 1, 2, 3, tzinfo=UTC)
WORKER = OnlyResearchWorkerInstanceId("00000000-0000-4000-8002-000000000001")


def _queued(ordinal: int, *, queued_at: datetime = NOW) -> OnlyResearchRun:
    spec = specification()
    resolution = OnlyResearchSpecificationResolver(registry()).resolve(spec)
    return OnlyResearchRun.queued(
        run_id=OnlyResearchRunId(f"00000000-0000-4000-8000-{ordinal:012d}"),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=queued_at,
    )


def _active(run: OnlyResearchRun, ordinal: int, lease_expires_at: datetime) -> OnlyResearchRunAttempt:
    return OnlyResearchRunAttempt(
        OnlyResearchRunAttemptId(f"00000000-0000-4000-8001-{ordinal:012d}"),
        run.run_id,
        1,
        OnlyResearchRunAttemptState.ACTIVE,
        WORKER,
        run.started_at or NOW,
        run.started_at or NOW,
        lease_expires_at,
    )


def test_diagnoses_all_operational_combinations_without_mutating_facts() -> None:
    fresh = OnlyResearchWorkerPresence(WORKER, NOW, NOW + timedelta(minutes=10), "0.8.5")
    no_worker = _queued(1)
    aged = _queued(2, queued_at=NOW - timedelta(minutes=20))
    running_gap = _queued(3).transition(OnlyResearchRunState.RUNNING, at=NOW)
    overdue = _queued(4).transition(OnlyResearchRunState.RUNNING, at=NOW)
    healthy = _queued(5).transition(OnlyResearchRunState.RUNNING, at=NOW)
    cancellation = (
        _queued(6)
        .transition(OnlyResearchRunState.RUNNING, at=NOW)
        .transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=1))
    )
    observed = NOW + timedelta(minutes=10)
    policy = OnlyResearchDiagnosticPolicy(
        queue_age_threshold=timedelta(minutes=5), worker_stale_after=timedelta(minutes=1)
    )
    cases = (
        (OnlyResearchRunOperationalRecord(no_worker, ()), (), OnlyResearchOperationalDiagnosisCode.NO_READY_WORKER),
        (OnlyResearchRunOperationalRecord(aged, ()), (fresh,), OnlyResearchOperationalDiagnosisCode.QUEUE_AGED),
        (
            OnlyResearchRunOperationalRecord(running_gap, ()),
            (fresh,),
            OnlyResearchOperationalDiagnosisCode.RUNNING_WITHOUT_ACTIVE_ATTEMPT,
        ),
        (
            OnlyResearchRunOperationalRecord(overdue, (_active(overdue, 4, observed),)),
            (fresh,),
            OnlyResearchOperationalDiagnosisCode.ACTIVE_LEASE_OVERDUE,
        ),
        (
            OnlyResearchRunOperationalRecord(healthy, (_active(healthy, 5, observed + timedelta(minutes=1)),)),
            (fresh,),
            OnlyResearchOperationalDiagnosisCode.HEALTHY,
        ),
        (
            OnlyResearchRunOperationalRecord(cancellation, ()),
            (fresh,),
            OnlyResearchOperationalDiagnosisCode.CANCELLATION_RECOVERY_PENDING,
        ),
    )
    service = OnlyResearchOperationalDiagnosticService(policy)
    for record, workers, expected in cases:
        before = record
        diagnosis = service.diagnose(OnlyResearchOperationalSnapshot(observed, workers, (record,)))
        assert diagnosis[0].code is expected
        assert record == before


def test_structured_event_is_stable_and_secret_free(caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.INFO):
        only_log_research_operational_event(
            logging.getLogger("test"),
            logging.INFO,
            "research.run.failed",
            run_id="run",
            attempt_id="attempt",
            worker_instance_id="worker",
            failure_code="SAFE_FAILURE",
        )
    rendered = caplog.text
    assert '"event":"research.run.failed"' in rendered
    assert '"run_id":"run"' in rendered and '"attempt_id":"attempt"' in rendered
    assert "password" not in rendered and "postgresql://" not in rendered
