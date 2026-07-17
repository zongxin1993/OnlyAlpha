"""Ordered integration scenarios."""

from collections.abc import Callable

from tests.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport

OnlyScenario = Callable[[OnlyIntegrationEnvironment], OnlyScenarioReport]

__all__ = ["OnlyScenario"]
