from examples.order_demo.common import only_fill, only_submit


def main() -> None:
    manager, _, _, _, submitted = only_submit()
    fill = only_fill(submitted.order_id, "same-trade", "40", 2)
    first = manager.apply_fill(fill)
    duplicate = manager.apply_fill(fill)
    print("first=", first.apply_result.value, "duplicate=", duplicate.apply_result.value)
    print(duplicate.snapshot.to_json())


if __name__ == "__main__":
    main()
