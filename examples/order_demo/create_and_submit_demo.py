from examples.order_demo.common import only_submit


def main() -> None:
    _, _, publisher, placeholder, result = only_submit()
    print(result.snapshot.to_json())
    print("events=", [str(event.event_type) for event in publisher.events])
    print("placeholder_submissions=", len(placeholder.submissions), "venue_accepted=", result.venue_accepted)


if __name__ == "__main__":
    main()
