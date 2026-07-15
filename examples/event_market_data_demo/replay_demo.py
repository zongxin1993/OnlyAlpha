"""The same versioned local input produces identical Replay projections."""

from examples.event_market_data_demo.common import run_minutes
from examples.integration_demo.environment import OnlyIntegrationEnvironment


def replay() -> tuple[object, ...]:
    env = OnlyIntegrationEnvironment()
    run_minutes(env)
    return env.deterministic_projection()


def main() -> None:
    assert replay() == replay()


if __name__ == "__main__":
    main()
