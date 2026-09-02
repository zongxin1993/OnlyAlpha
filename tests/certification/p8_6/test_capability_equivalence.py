from __future__ import annotations

import pytest
from onlyalpha_http_server.main import _configure_calculation_registry

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationRegistry,
    only_assert_calculation_capabilities_equivalent,
    only_calculation_capability_projection,
)
from onlyalpha.runtime.defaults import only_default_engine_services


def _research_projection(registry: OnlyCalculationRegistry):
    return only_calculation_capability_projection(registry, OnlyCalculationBackendKind.RESEARCH)


def _api_calculation_registry() -> OnlyCalculationRegistry:
    registry = OnlyCalculationRegistry()
    _configure_calculation_registry(registry)
    return registry


def test_api_and_worker_startup_expose_the_same_research_semantic_capabilities() -> None:
    api = _research_projection(_api_calculation_registry())
    worker_services = only_default_engine_services(fail_fast=True)
    worker = _research_projection(worker_services.assembler.components.calculations)

    only_assert_calculation_capabilities_equivalent(api, worker)
    assert api
    assert api == tuple(sorted(api, key=lambda item: (item.type_definition.kind.value, item.type_definition.type_id)))


def test_research_semantic_capability_drift_fails_closed() -> None:
    expected = _research_projection(_api_calculation_registry())
    actual = _research_projection(OnlyCalculationRegistry())

    with pytest.raises(ValueError, match="semantic capability mismatch"):
        only_assert_calculation_capabilities_equivalent(expected, actual)
