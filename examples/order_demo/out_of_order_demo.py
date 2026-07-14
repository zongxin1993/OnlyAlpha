from examples.order_demo.common import only_fill, only_submit
from onlyalpha.domain.identifiers import OnlyVenueOrderId
from onlyalpha.domain.time import OnlyTimestamp


def main() -> None:
    manager, _, _, _, submitted = only_submit()
    filled_first = manager.apply_fill(only_fill(submitted.order_id, "trade-before-accepted", "40", 3))
    accepted_late = manager.apply_accepted(
        submitted.order_id,
        OnlyTimestamp.from_unix_nanos(2),
        OnlyVenueOrderId("venue-1"),
        event_time=OnlyTimestamp.from_unix_nanos(2),
    )
    print("before=", filled_first.current_status.value, "after=", accepted_late.current_status.value)
    print(accepted_late.snapshot.to_json())


if __name__ == "__main__":
    main()
