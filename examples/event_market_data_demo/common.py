"""Shared fixtures using the formal historical Replay ingress."""

from examples.integration_demo.environment import DAY_ONE, OnlyIntegrationEnvironment


def run_minutes(env: OnlyIntegrationEnvironment, count: int = 3) -> None:
    env.start()
    for minute in range(count):
        env.process_bar(DAY_ONE, minute, f"10.0{minute}")
