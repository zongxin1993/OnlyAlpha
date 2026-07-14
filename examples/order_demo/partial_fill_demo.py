from examples.order_demo.common import only_fill, only_submit
from onlyalpha.domain.identifiers import OnlyVenueOrderId
from onlyalpha.domain.time import OnlyTimestamp


def main() -> None:
    manager, _, _, _, submitted = only_submit()
    manager.apply_accepted(submitted.order_id, OnlyTimestamp.from_unix_nanos(2), OnlyVenueOrderId("venue-1"))
    first = manager.apply_fill(only_fill(submitted.order_id, "trade-40", "40", 3))
    final = manager.apply_fill(only_fill(submitted.order_id, "trade-60", "60", 4))
    print(first.snapshot.to_json())
    print(final.snapshot.to_json())


if __name__ == "__main__":
    main()
