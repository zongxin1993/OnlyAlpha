from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.identifiers import (
    OnlyDataVersion,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.runtime.checkpoint.codec import (
    only_create_checkpoint_component,
    only_decode_checkpoint_component,
)
from onlyalpha.runtime.checkpoint.model import (
    OnlyBacktestReplayCursor,
    OnlyCheckpointCaptureContext,
    OnlyCheckpointRestoreContext,
)
from onlyalpha.runtime.checkpoint.participant import (
    OnlyJsonRuntimeCheckpointParticipant,
    OnlyStatelessRuntimeCheckpointParticipant,
)
from onlyalpha.runtime.checkpoint.registry import OnlyRuntimeCheckpointParticipantRegistry


def _cursor() -> OnlyBacktestReplayCursor:
    return OnlyBacktestReplayCursor(
        OnlyMarketDataSourceId("source"),
        OnlyDataVersion("v1"),
        OnlyMarketDataUpdateId("update-1"),
        1,
        OnlyTimestamp.from_unix_nanos(1),
        1,
    )


def test_participant_capture_mutate_restore_equality_and_stable_order() -> None:
    state = {"value": 7}

    def restore(payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("test checkpoint must be an object")
        state["value"] = int(payload["value"])

    registry = OnlyRuntimeCheckpointParticipantRegistry()
    registry.register(
        OnlyJsonRuntimeCheckpointParticipant(
            "z.component",
            1,
            lambda: dict(state),
            restore,
        )
    )
    registry.register(OnlyJsonRuntimeCheckpointParticipant("a.stateless", 1, lambda: {}, lambda _: None))
    runtime_id = OnlyRuntimeId("runtime")
    components = registry.capture(
        OnlyCheckpointCaptureContext(runtime_id, OnlyTimestamp.from_unix_nanos(2), _cursor(), 0)
    )
    assert tuple(item.component_id for item in components) == ("a.stateless", "z.component")
    state["value"] = 99
    registry.restore(components, OnlyCheckpointRestoreContext(runtime_id, _cursor()))
    assert state == {"value": 7}


def test_component_codec_rejects_noncanonical_or_corrupt_payload() -> None:
    component = only_create_checkpoint_component("component", 1, {"b": 2, "a": 1})
    assert component.payload == '{"a":1,"b":2}'
    assert only_decode_checkpoint_component(component) == {"a": 1, "b": 2}
    corrupted = type(component)(
        component.component_id, component.component_schema_version, "{}", component.payload_hash
    )
    try:
        only_decode_checkpoint_component(corrupted)
    except ValueError as exc:
        assert "hash" in str(exc).lower()
    else:
        raise AssertionError("corrupt checkpoint component was accepted")


def test_registry_rejects_duplicate_and_missing_component() -> None:
    registry = OnlyRuntimeCheckpointParticipantRegistry()
    participant = OnlyJsonRuntimeCheckpointParticipant("component", 1, lambda: {}, lambda _: None)
    registry.register(participant)
    try:
        registry.register(participant)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate participant was accepted")
    try:
        registry.validate_components(())
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("missing checkpoint component was accepted")


def test_explicit_stateless_participant_affects_registry_identity_without_component_payload() -> None:
    registry = OnlyRuntimeCheckpointParticipantRegistry()
    registry.register(OnlyStatelessRuntimeCheckpointParticipant("data-source.history"))
    fingerprint = registry.fingerprint
    components = registry.capture(
        OnlyCheckpointCaptureContext(OnlyRuntimeId("runtime"), OnlyTimestamp.from_unix_nanos(2), _cursor(), 0)
    )
    assert components == ()
    assert fingerprint == registry.fingerprint
    registry.restore((), OnlyCheckpointRestoreContext(OnlyRuntimeId("runtime"), _cursor()))


def test_clock_checkpoint_restores_timer_deadline_sequence_and_fire_count() -> None:
    fired: list[tuple[int, int]] = []
    original = OnlyBacktestClock(0)
    original.schedule_every("cluster:timer", 10, lambda event: fired.append((event.sequence, event.fire_count)))
    original.advance_to(10)
    snapshot = original.snapshot()

    restored = OnlyBacktestClock(0)
    restored.schedule_every("cluster:timer", 99, lambda event: fired.append((event.sequence, event.fire_count)))
    restored.restore_with_registered_callbacks(snapshot)
    result = restored.advance_to(20)
    assert tuple((item.sequence, item.fire_count) for item in result.fired_events) == ((1, 2),)
