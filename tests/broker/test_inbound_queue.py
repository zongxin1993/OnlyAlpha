from datetime import UTC, datetime

import pytest

from onlyalpha.broker import (
    OnlyBoundedBrokerInboundQueue,
    OnlyBrokerGatewayId,
    OnlyBrokerInboundQueueFullError,
    OnlyBrokerUpdateId,
)
from onlyalpha.broker.updates import OnlyBrokerInboundUpdate
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp


def _update(sequence: int) -> OnlyBrokerInboundUpdate:
    timestamp = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))
    return OnlyBrokerInboundUpdate(
        runtime_id=OnlyRuntimeId("runtime"),
        gateway_id=OnlyBrokerGatewayId("gateway"),
        account_id=OnlyAccountId("account"),
        update_id=OnlyBrokerUpdateId(f"update-{sequence}"),
        source_sequence=sequence,
        ts_event=timestamp,
        ts_init=timestamp,
        correlation_id=str(sequence),
        causation_id="test",
    )


def test_broker_inbound_queue_is_bounded_fifo_and_drains_atomically() -> None:
    queue = OnlyBoundedBrokerInboundQueue(2)
    first = _update(1)
    second = _update(2)
    queue.put(first)
    queue.put(second)

    with pytest.raises(OnlyBrokerInboundQueueFullError):
        queue.put(_update(3))

    assert len(queue) == 2
    assert queue.drain() == (first, second)
    assert len(queue) == 0
