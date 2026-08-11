from dataclasses import replace

import pytest

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.runtime.checkpoint.codec import only_seal_runtime_checkpoint
from onlyalpha.runtime.checkpoint.model import (
    ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
    OnlyBacktestReplayCursor,
    OnlyRuntimeCheckpointHeader,
)
from onlyalpha.runtime.recovery.orchestrator import OnlyRuntimeRecoveryDiagnostic, OnlyRuntimeRecoveryStatus
from onlyalpha.runtime.recovery.outcome import OnlyRuntimeRecoveryOutcome


def _outcome() -> OnlyRuntimeRecoveryOutcome:
    cursor = OnlyBacktestReplayCursor(OnlyMarketDataSourceId("source"), OnlyDataVersion("version"), None, 0, None, 0)
    header = OnlyRuntimeCheckpointHeader(
        OnlyRuntimeId("runtime"),
        1,
        0,
        ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
        OnlyTimestamp.from_unix_nanos(1),
        cursor,
        "config",
        "0" * 64,
        "registry",
        "pending",
    )
    checkpoint = only_seal_runtime_checkpoint(header, ())
    diagnostic = OnlyRuntimeRecoveryDiagnostic(
        OnlyRuntimeRecoveryStatus.RESTORED,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        None,
    )
    return OnlyRuntimeRecoveryOutcome(checkpoint, diagnostic, None, None, None, None, None, False)


def test_empty_recovery_ranges_are_explicit() -> None:
    outcome = _outcome()
    assert outcome.persisted_tail_start_sequence is None
    assert outcome.continuation_end_sequence is None
    assert not outcome.replay_performed


def test_outcome_rejects_half_open_ranges_and_missing_replay_boundary() -> None:
    outcome = _outcome()
    with pytest.raises(ValueError, match="endpoints"):
        replace(outcome, persisted_tail_start_sequence=1)
    with pytest.raises(ValueError, match="final boundary"):
        replace(outcome, replay_performed=True)
