from tests.integration_demo.environment import OnlyIntegrationEnvironment
from tests.integration_demo.run_all import SCENARIOS


def replay() -> tuple[object, ...]:
    env = OnlyIntegrationEnvironment()
    for scenario in SCENARIOS:
        scenario(env)
    return env.deterministic_projection()


def test_full_vertical_slice_replay_is_deterministic() -> None:
    baseline = replay()
    for _ in range(100):
        assert replay() == baseline
