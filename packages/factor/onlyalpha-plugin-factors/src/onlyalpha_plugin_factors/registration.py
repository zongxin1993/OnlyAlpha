"""Deterministic empty provider until an official concrete Factor exists."""

from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration


def registrations() -> tuple[OnlyCalculationBackendRegistration, ...]:
    return ()
