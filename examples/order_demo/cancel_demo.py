from examples.order_demo.common import only_submit
from onlyalpha.domain.execution import OnlyCancelOrderRequest
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyOrderRequestId, OnlyVenueOrderId
from onlyalpha.domain.time import OnlyTimestamp


def main() -> None:
    manager, service, _, _, submitted = only_submit()
    manager.apply_accepted(submitted.order_id, OnlyTimestamp.from_unix_nanos(2), OnlyVenueOrderId("venue-1"))
    pending = service.cancel(
        OnlyCancelOrderRequest(OnlyOrderRequestId("cancel-request"), submitted.order_id),
        OnlyClusterId("demo"),
    )
    cancelled = manager.apply_cancelled(submitted.order_id, OnlyTimestamp.from_unix_nanos(3))
    print(pending.snapshot.to_json())
    print(cancelled.snapshot.to_json())


if __name__ == "__main__":
    main()
