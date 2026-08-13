from unittest.mock import Mock

import pytest

from onlyalpha.core.clock import OnlyBacktestClock, OnlyTimerId
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from onlyalpha.runtime.streaming.timer_registry import (
    OnlyRuntimeTimerLogicalState,
    OnlyRuntimeTimerRegistry,
)

pytestmark = [pytest.mark.unit, pytest.mark.sim_recovery]


def _registry(clock, store, fired):  # type: ignore[no-untyped-def]
    return OnlyRuntimeTimerRegistry(
        OnlyRuntimeId("runtime"),
        clock,
        store,
        lambda occurrence, event, callback, complete: (
            fired.append((occurrence, event)),
            callback(event),
            complete(),
        ),
    )


def test_timer_occurrence_is_admitted_before_callback_and_checkpoint_can_cover_it() -> None:
    clock = OnlyBacktestClock(0)
    store = OnlyInMemoryRuntimePersistenceStore()
    fired = []
    callback = Mock(side_effect=lambda event: fired.append(("callback", event)))
    registry = _registry(clock, store, fired)
    registry.schedule_at(OnlyTimerId("runtime:cluster:timer"), OnlyClusterId("cluster"), 10, callback)

    clock.advance_to(10)

    assert len(store.unresolved(OnlyRuntimeId("runtime"))) == 1
    assert fired[0][0] == store.unresolved(OnlyRuntimeId("runtime"))[0]
    assert fired[1][0] == "callback"
    assert registry.definitions[0].state is OnlyRuntimeTimerLogicalState.COMPLETED
    store.cover(OnlyRuntimeId("runtime"), 1)
    assert store.unresolved(OnlyRuntimeId("runtime")) == ()


def test_restore_skips_downtime_recurring_occurrences_and_marks_expired_one_shot_missed() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    original_clock = OnlyBacktestClock(0)
    original = _registry(original_clock, store, [])
    original.schedule_every(
        OnlyTimerId("runtime:cluster:recurring"),
        OnlyClusterId("cluster"),
        10,
        lambda event: None,
        start_ns=10,
    )
    original.schedule_at(OnlyTimerId("runtime:cluster:once"), OnlyClusterId("cluster"), 15, lambda event: None)
    payload = original.capture_checkpoint()

    restored_clock = OnlyBacktestClock(100)
    restored = _registry(restored_clock, store, [])
    restored.restore_checkpoint(payload)
    restored.rearm_after_restore(
        {
            OnlyTimerId("runtime:cluster:recurring"): lambda event: None,
            OnlyTimerId("runtime:cluster:once"): lambda event: None,
        }
    )

    definitions = {str(item.timer_id): item for item in restored.definitions}
    assert definitions["runtime:cluster:once"].state is OnlyRuntimeTimerLogicalState.MISSED
    assert definitions["runtime:cluster:recurring"].next_deadline_ns == 110
    assert store.unresolved(OnlyRuntimeId("runtime")) == ()
    restored_clock.advance_to(109)
    assert store.unresolved(OnlyRuntimeId("runtime")) == ()
    restored_clock.advance_to(110)
    assert len(store.unresolved(OnlyRuntimeId("runtime"))) == 1


def test_timer_checkpoint_excludes_clock_wall_and_monotonic_state() -> None:
    registry = _registry(OnlyBacktestClock(0), OnlyInMemoryRuntimePersistenceStore(), [])
    registry.schedule_at(OnlyTimerId("runtime:cluster:timer"), OnlyClusterId("cluster"), 10, lambda event: None)
    payload = str(registry.capture_checkpoint()).lower()
    assert "monotonic" not in payload
    assert "current_timestamp" not in payload


def test_restore_cancels_process_local_handles_until_explicit_rearm() -> None:
    clock = OnlyBacktestClock(0)
    registry = _registry(clock, OnlyInMemoryRuntimePersistenceStore(), [])
    callback = Mock()
    registry.schedule_at(OnlyTimerId("runtime:cluster:timer"), OnlyClusterId("cluster"), 10, callback)

    registry.restore_checkpoint(registry.capture_checkpoint())
    clock.advance_to(10)

    callback.assert_not_called()
