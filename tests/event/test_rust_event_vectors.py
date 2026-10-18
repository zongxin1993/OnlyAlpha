"""Independent common behavior; known Python deviations are not equivalence targets."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.event.bus import (
    OnlyEventBus,
    OnlyEventBusError,
    OnlyEventCapacityError,
    OnlyEventQueuePolicy,
    OnlyEventRuntimeFailure,
    OnlyEventScopeError,
)
from onlyalpha.event.model import OnlyEvent, OnlyEventPriority, OnlyEventScope
from onlyalpha.event.ports import OnlyRuntimeEventDisposition, OnlyRuntimeEventPublicationResult, OnlyRuntimeEventRoute

ROOT = Path(__file__).resolve().parents[2]


def test_event_current_records_preserve_independent_expected_values() -> None:
    for line in (ROOT / "test-data/event/records-v2.jsonl").read_text().splitlines():
        case = json.loads(line)
        assert OnlyEvent.from_dict(case["record"]).to_dict() == case["record"], case["name"]


def _event(action: dict[str, object]) -> OnlyEvent:
    sequence = int(str(action["sequence"]))
    return OnlyEvent(
        "FACT",
        datetime(1970, 1, 1, tzinfo=UTC),
        "engine",
        str(action["runtime"]),
        "feed",
        sequence,
        event_id=UUID(int=sequence),
        priority=OnlyEventPriority[str(action["priority"])],
    )


def test_event_delivery_matches_independent_expected_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    for line in (ROOT / "test-data/event/delivery-v1.jsonl").read_text().splitlines():
        case = json.loads(line)
        bus = OnlyEventBus(
            case["capacity"],
            scope=OnlyEventScope(OnlyEngineId("engine"), OnlyRuntimeId("runtime")),
            queue_policy=OnlyEventQueuePolicy(case["policy"]),
        )
        errors: list[str] = []
        ids: Iterator[UUID] = iter(UUID(action["id"]) for action in case["actions"] if action["op"] == "subscribe")
        monkeypatch.setattr("onlyalpha.event.bus.uuid4", lambda allocated=ids: next(allocated))
        for index, action in enumerate(case["actions"]):
            try:
                if action["op"] == "subscribe":

                    def handler(_: OnlyEvent, fail: bool = action["fail"]) -> None:
                        if fail:
                            raise RuntimeError("controlled failure")

                    handler.__qualname__ = action["name"]
                    bus.subscribe("FACT", handler, priority=OnlyEventPriority[action["priority"]])
                elif action["op"] == "unsubscribe":
                    from onlyalpha.event.bus import OnlySubscriptionId

                    bus.unsubscribe(OnlySubscriptionId(UUID(action["id"])))
                elif action["op"] == "publish":
                    bus.publish(_event(action))
                elif action["op"] == "batch":
                    batch = tuple(_event(item) for item in action["events"])
                    if action["atomic"]:
                        bus.publish_many_atomic(batch)
                    else:
                        bus.publish_many(batch)
                elif action["op"] == "drain":
                    bus.drain()
                elif action["op"] == "close":
                    bus.close()
                else:
                    assert action["op"] == "port_result"
                    OnlyRuntimeEventPublicationResult(
                        OnlyRuntimeEventRoute.EXTERNAL_DIRECT,
                        OnlyRuntimeEventDisposition.PUBLISHED,
                        action["attempted"],
                        action["published"],
                        0,
                        0,
                        0,
                    )
            except (OnlyEventBusError, ValueError) as error:
                category = (
                    "SCOPE"
                    if isinstance(error, OnlyEventScopeError)
                    else "RUNTIME_FAILURE"
                    if isinstance(error, OnlyEventRuntimeFailure)
                    else "CAPACITY"
                    if isinstance(error, OnlyEventCapacityError)
                    else "CLOSED"
                    if isinstance(error, OnlyEventBusError)
                    else "INVALID"
                )
                errors.append(f"{index}:{category}")
        outcomes = [
            f"{report.event.event_id}|{result.subscription_id}|{result.handler_name}|{'OK' if result.succeeded else 'ERR'}"
            for report in bus.dispatch_results
            for result in report.handler_results
        ]
        actual = {
            "outcomes": outcomes,
            "errors": errors,
            "dropped": [f"{drop.dropped.event_id}|{drop.accepted.event_id}" for drop in bus.dropped_events],
            "pending": bus.pending_count(),
        }
        assert actual == case["expected"], case["name"]
