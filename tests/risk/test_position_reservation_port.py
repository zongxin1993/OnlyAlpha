from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.order.service import OnlyOrderService


class OnlyRecordingPositionReservationPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, OnlyOrderId]] = []

    def reserve(self, order: OnlyOrderSnapshot, timestamp: OnlyTimestamp) -> None:
        del timestamp
        self.calls.append(("reserve", order.order_id))

    def sent(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        del timestamp
        self.calls.append(("sent", order_id))

    def acknowledged(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        del timestamp
        self.calls.append(("acknowledged", order_id))

    def consume(self, order_id: OnlyOrderId, quantity: OnlyQuantity, timestamp: OnlyTimestamp) -> None:
        del quantity, timestamp
        self.calls.append(("consume", order_id))

    def release(
        self,
        order_id: OnlyOrderId,
        timestamp: OnlyTimestamp,
        *,
        broker_confirmed: bool,
    ) -> None:
        del timestamp, broker_confirmed
        self.calls.append(("release", order_id))


def test_order_service_reserves_position_before_marking_order_submitted(build_harness, order_request) -> None:
    harness = build_harness()
    port = OnlyRecordingPositionReservationPort()
    service = OnlyOrderService(
        harness.manager,
        harness.execution,
        harness.order_publisher,
        lambda: OnlyTimestamp.from_unix_nanos(harness.clock.timestamp_ns()),
        harness.risk,
        harness.risk.make_evaluation_context,
        port,
    )

    result = service.submit(order_request, harness.cluster_id, harness.account_id)

    assert result.submitted and result.order_id is not None
    assert port.calls == [("reserve", result.order_id), ("sent", result.order_id)]
