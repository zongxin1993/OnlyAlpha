from threading import Event, Thread

import pytest

from onlyalpha.runtime.streaming.phase import OnlyStreamingPhase
from onlyalpha.runtime.streaming.phase_controller import OnlyStreamingPhaseController

pytestmark = pytest.mark.unit


def test_stopping_has_precedence_over_recovery_transitions() -> None:
    controller = OnlyStreamingPhaseController(OnlyStreamingPhase.LIVE)
    assert controller.begin_stop()

    for target in (
        OnlyStreamingPhase.DEGRADED,
        OnlyStreamingPhase.RECOVERING,
        OnlyStreamingPhase.CATCH_UP,
        OnlyStreamingPhase.LIVE,
    ):
        assert not controller.transition(set(OnlyStreamingPhase), target)
    assert controller.snapshot().phase is OnlyStreamingPhase.STOPPING
    assert controller.transition({OnlyStreamingPhase.STOPPING}, OnlyStreamingPhase.STOPPED)


def test_wait_for_requires_a_new_target_revision() -> None:
    controller = OnlyStreamingPhaseController(OnlyStreamingPhase.LIVE)
    before = controller.snapshot()
    waiting = Event()
    result = []

    def wait() -> None:
        waiting.set()
        result.append(controller.wait_for(OnlyStreamingPhase.LIVE, after_revision=before.revision, timeout=3))

    thread = Thread(target=wait)
    thread.start()
    assert waiting.wait(1)
    assert controller.transition({OnlyStreamingPhase.LIVE}, OnlyStreamingPhase.DEGRADED)
    assert controller.transition({OnlyStreamingPhase.DEGRADED}, OnlyStreamingPhase.RECOVERING)
    assert controller.transition({OnlyStreamingPhase.RECOVERING}, OnlyStreamingPhase.CATCH_UP)
    assert controller.transition({OnlyStreamingPhase.CATCH_UP}, OnlyStreamingPhase.LIVE)
    thread.join(3)

    assert result[0] is not None
    assert result[0].phase is OnlyStreamingPhase.LIVE
    assert result[0].revision > before.revision
