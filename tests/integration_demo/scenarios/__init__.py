"""Ordered integration scenarios."""

from collections.abc import Callable

from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport

OnlyScenario = Callable[[OnlyIntegrationEnvironment], OnlyScenarioReport]

__all__ = ["OnlyScenario"]
