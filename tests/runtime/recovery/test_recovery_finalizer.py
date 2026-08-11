from dataclasses import replace

import pytest

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.runtime.checkpoint.codec import only_seal_runtime_checkpoint
from onlyalpha.runtime.checkpoint.model import (
    ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
    OnlyBacktestReplayCursor,
    OnlyRuntimeCheckpointHeader,
)
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from onlyalpha.runtime.recovery.authority_views import OnlyRuntimeBoundaryAuthorityView
from onlyalpha.runtime.recovery.finalizer import (
    OnlyRuntimeRecoveryFinalizationError,
    OnlyRuntimeRecoveryFinalizationPhase,
    OnlyRuntimeRecoveryFinalizer,
)
from onlyalpha.runtime.recovery.orchestrator import OnlyRuntimeRecoveryDiagnostic, OnlyRuntimeRecoveryStatus
from onlyalpha.runtime.recovery.outcome import OnlyRuntimeRecoveryOutcome
from onlyalpha.runtime.recovery.validation import (
    OnlyPostRecoveryCheckStatus,
    OnlyPostRecoveryValidationCheck,
    OnlyPostRecoveryValidationContext,
    OnlyPostRecoveryValidationReport,
)
from onlyalpha.transaction.applied_projection import OnlyInMemoryAppliedRuntimeProjectionLedger


class OnlyTestClusterFinalizationManager:
    def __init__(self) -> None:
        self.state = "RECOVERING"
        self.cleaned = False

    def begin_recovery_finalization_all(self) -> None:
        assert self.state == "RECOVERING"
        self.state = "RECOVERY_FINALIZING"

    def mark_recovered_all(self) -> None:
        assert self.state == "RECOVERY_FINALIZING"
        self.state = "RECOVERED"

    def fail_recovery_finalization_all(self, error: Exception) -> None:
        del error
        self.state = "FAILED"
        self.cleaned = True


class OnlyTestValidator:
    def __init__(self, passed: bool = True) -> None:
        self._passed = passed
        self.calls = 0

    def validate(self, context: OnlyPostRecoveryValidationContext) -> OnlyPostRecoveryValidationReport:
        self.calls += 1
        return OnlyPostRecoveryValidationReport(
            context.runtime_id,
            (
                OnlyPostRecoveryValidationCheck(
                    "TEST_AUTHORITY",
                    OnlyPostRecoveryCheckStatus.PASSED if self._passed else OnlyPostRecoveryCheckStatus.FAILED,
                    "runtime",
                    "stable",
                    "stable" if self._passed else "corrupt",
                    "test authority",
                ),
            ),
        )


class OnlyTestCheckpointService:
    def __init__(self, checkpoint, failure: str | None = None) -> None:  # type: ignore[no-untyped-def]
        self.checkpoint = checkpoint
        self.failure = failure
        self.calls: list[str] = []

    def capture(self, cursor, created_at):  # type: ignore[no-untyped-def]
        del cursor, created_at
        self.calls.append("capture")
        if self.failure == "capture":
            raise RuntimeError("capture failed")
        return self.checkpoint

    def write(self, checkpoint):  # type: ignore[no-untyped-def]
        assert checkpoint == self.checkpoint
        self.calls.append("write")
        if self.failure == "write":
            raise RuntimeError("write failed")

    def verify_durable(self, checkpoint):  # type: ignore[no-untyped-def]
        assert checkpoint == self.checkpoint
        self.calls.append("verify")
        if self.failure in {"write", "verify"}:
            raise RuntimeError("not durable")
        return checkpoint


def _fixture(
    failure: str | None = None,
    *,
    validation_passed: bool = True,
    broker_inbound_count: int = 0,
    market_data_inbound_count: int = 0,
    event_bus_pending_count: int = 0,
):  # type: ignore[no-untyped-def]
    runtime_id = OnlyRuntimeId("runtime")
    cursor = OnlyBacktestReplayCursor(OnlyMarketDataSourceId("source"), OnlyDataVersion("version"), None, 0, None, 0)
    checkpoint = only_seal_runtime_checkpoint(
        OnlyRuntimeCheckpointHeader(
            runtime_id,
            1,
            0,
            ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
            OnlyTimestamp.from_unix_nanos(1),
            cursor,
            "config",
            "0" * 64,
            "registry",
            "pending",
        ),
        (),
    )
    diagnostic = OnlyRuntimeRecoveryDiagnostic(
        OnlyRuntimeRecoveryStatus.RESTORED, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, None
    )
    outcome = OnlyRuntimeRecoveryOutcome(checkpoint, diagnostic, None, None, None, None, None, False)
    store = OnlyInMemoryRuntimePersistenceStore()
    context = OnlyPostRecoveryValidationContext(
        runtime_id,
        outcome,
        store,
        store,
        store,
        OnlyInMemoryAppliedRuntimeProjectionLedger(),
        OnlyRuntimeBoundaryAuthorityView(
            runtime_id,
            broker_inbound_count,
            market_data_inbound_count,
            event_bus_pending_count,
            cursor,
            0,
            0,
            0,
            OnlyTimestamp.from_unix_nanos(1),
        ),
    )
    manager = OnlyTestClusterFinalizationManager()
    service = OnlyTestCheckpointService(checkpoint, failure)
    validator = OnlyTestValidator(validation_passed)
    finalizer = OnlyRuntimeRecoveryFinalizer(
        cluster_manager=manager,  # type: ignore[arg-type]
        event_bus=OnlyEventBus(),
        validator=validator,  # type: ignore[arg-type]
        context_factory=lambda _: context,
        checkpoint_service=service,  # type: ignore[arg-type]
        replay_cursor=lambda: cursor,
        created_at=lambda: OnlyTimestamp.from_unix_nanos(1),
    )
    return outcome, manager, service, validator, finalizer


def test_finalizer_marks_recovered_only_after_read_back() -> None:
    outcome, manager, service, _, finalizer = _fixture()
    result = finalizer.finalize(outcome)
    assert result.validation_report.passed
    assert service.calls == ["capture", "write", "verify"]
    assert manager.state == "RECOVERED"
    assert finalizer.phase is OnlyRuntimeRecoveryFinalizationPhase.COMPLETED


@pytest.mark.parametrize(
    "failure,phase",
    (
        ("capture", OnlyRuntimeRecoveryFinalizationPhase.CHECKPOINT_CAPTURE),
        ("write", OnlyRuntimeRecoveryFinalizationPhase.CHECKPOINT_WRITE),
        ("verify", OnlyRuntimeRecoveryFinalizationPhase.CHECKPOINT_VERIFY),
    ),
)
def test_finalizer_failures_clean_cluster_and_fail_closed(failure: str, phase) -> None:  # type: ignore[no-untyped-def]
    outcome, manager, _, _, finalizer = _fixture(failure)
    with pytest.raises(OnlyRuntimeRecoveryFinalizationError) as caught:
        finalizer.finalize(outcome)
    assert caught.value.phase is phase
    assert manager.state == "FAILED"
    assert manager.cleaned
    assert finalizer.phase is OnlyRuntimeRecoveryFinalizationPhase.FAILED


def test_validation_failure_never_captures_checkpoint() -> None:
    outcome, manager, service, _, finalizer = _fixture(validation_passed=False)
    with pytest.raises(OnlyRuntimeRecoveryFinalizationError) as caught:
        finalizer.finalize(outcome)
    assert caught.value.phase is OnlyRuntimeRecoveryFinalizationPhase.AUTHORITY_VALIDATION
    assert service.calls == []
    assert manager.state == "FAILED"


def test_finalizer_cannot_run_twice() -> None:
    outcome, _, _, _, finalizer = _fixture()
    finalizer.finalize(outcome)
    with pytest.raises(OnlyRuntimeRecoveryFinalizationError):
        finalizer.finalize(replace(outcome))


@pytest.mark.parametrize(
    "counts,code",
    (
        ((1, 0, 0), "POST_RECOVERY_INBOUND_QUEUE_NOT_EMPTY"),
        ((0, 1, 0), "POST_RECOVERY_INBOUND_QUEUE_NOT_EMPTY"),
        ((0, 0, 1), "POST_RECOVERY_EVENT_BUS_NOT_DRAINED"),
    ),
)
def test_quiescence_failure_is_precise_and_prevents_validation_and_checkpoint(
    counts: tuple[int, int, int], code: str
) -> None:
    outcome, manager, service, validator, finalizer = _fixture(
        broker_inbound_count=counts[0],
        market_data_inbound_count=counts[1],
        event_bus_pending_count=counts[2],
    )
    with pytest.raises(OnlyRuntimeRecoveryFinalizationError) as caught:
        finalizer.finalize(outcome)
    assert caught.value.phase is OnlyRuntimeRecoveryFinalizationPhase.QUIESCENCE_CHECK
    assert caught.value.original_error_message == code
    assert validator.calls == 0
    assert service.calls == []
    assert manager.state == "FAILED"
