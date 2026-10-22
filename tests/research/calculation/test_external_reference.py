"""External algorithm reference claims retained after deferred HTTP retirement."""

from __future__ import annotations

from decimal import Decimal

import pyarrow as pa  # type: ignore[import-untyped]
from onlyalpha_test_plugin.research_calculation import (
    EXTERNAL_IDENTITY,
    OnlyExternalIdentityDefinitionResolver,
    OnlyExternalIdentityResearchBackend,
    registrations,
)

from onlyalpha.calculation import OnlyCalculationReference
from onlyalpha.calculation.registry import OnlyCalculationRegistry


def test_registered_external_algorithm_retains_exact_type_output_and_decimal_values() -> None:
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        registry.register(registration)
    assert EXTERNAL_IDENTITY.type_id in {item.type_id for item in registry.type_definitions()}
    definition = OnlyExternalIdentityDefinitionResolver().resolve(
        {}, {"value": OnlyCalculationReference(None, "close", "bar.close")}
    )
    values = pa.array([Decimal("1.25"), Decimal("-2.50")], type=pa.decimal128(38, 12))
    result = OnlyExternalIdentityResearchBackend().execute(definition, {"value": values})
    assert set(result) == {"value"}
    assert result["value"].equals(values)
