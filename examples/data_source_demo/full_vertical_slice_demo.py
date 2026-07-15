from examples.integration_demo.run_all import run_all


def main() -> None:
    reports = run_all()
    assert len(reports) == 33 and all(item.passed for item in reports)


if __name__ == "__main__":
    main()
