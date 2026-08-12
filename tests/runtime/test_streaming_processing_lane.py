from threading import Event, Thread
from unittest.mock import Mock, call

import pytest

from onlyalpha.runtime.streaming.semantic_lane import OnlyStreamingSemanticLane

pytestmark = pytest.mark.unit


def test_revoke_waits_for_atomic_commit_then_prevents_next_update() -> None:
    processor = Mock()
    processor.process.side_effect = ("first-result", "forbidden-result")
    lane = OnlyStreamingSemanticLane(processor)
    entered_commit = Event()
    release_commit = Event()
    first_outcome = []

    def commit(update: object, result: object) -> None:
        entered_commit.set()
        assert release_commit.wait(3)

    processing = Thread(target=lambda: first_outcome.append(lane.process("first", commit)))  # type: ignore[arg-type]
    processing.start()
    assert entered_commit.wait(3)

    revoked = Event()
    revoker = Thread(target=lambda: (lane.revoke(), revoked.set()))
    revoker.start()
    assert not revoked.wait(0.05)
    release_commit.set()
    processing.join(3)
    revoker.join(3)

    assert revoked.is_set()
    assert first_outcome[0].started
    assert not lane.process("second", commit).started  # type: ignore[arg-type]
    assert processor.process.call_args_list == [call("first")]


def test_commit_failure_remains_inside_atomic_processing_boundary() -> None:
    processor = Mock()
    processor.process.return_value = "result"
    lane = OnlyStreamingSemanticLane(processor)

    with pytest.raises(RuntimeError, match="commit failed"):
        lane.process("update", lambda update, result: (_ for _ in ()).throw(RuntimeError("commit failed")))  # type: ignore[arg-type]

    lane.revoke()
    assert lane.revoked


def test_cutoff_publication_and_revocation_share_the_processing_permission() -> None:
    processor = Mock()
    processor.process.return_value = "result"
    lane = OnlyStreamingSemanticLane(processor)
    cutoff_visible = Event()
    release_cutoff = Event()

    def establish_cutoff() -> None:
        cutoff_visible.set()
        assert release_cutoff.wait(3)

    revoker = Thread(target=lambda: lane.revoke(establish_cutoff))
    revoker.start()
    assert cutoff_visible.wait(3)
    outcome = []
    contender = Thread(target=lambda: outcome.append(lane.process("late", lambda update, result: None)))  # type: ignore[arg-type]
    contender.start()
    assert outcome == []
    release_cutoff.set()
    revoker.join(3)
    contender.join(3)

    assert not outcome[0].started
    processor.process.assert_not_called()


def test_generic_semantic_actions_share_the_same_stop_cutoff() -> None:
    lane = OnlyStreamingSemanticLane(Mock())
    mutations: list[str] = []

    assert lane.execute(lambda: mutations.append("timer")).started
    lane.revoke()
    assert not lane.execute(lambda: mutations.append("late-checkpoint")).started
    assert mutations == ["timer"]
