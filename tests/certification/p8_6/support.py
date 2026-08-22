from __future__ import annotations

from dataclasses import replace

from onlyalpha_test_plugin.research_calculation import EXTERNAL_IDENTITY

from onlyalpha.calculation import OnlyCalculationKind, OnlyCalculationTypeReference
from onlyalpha.research import OnlyResearchCalculationInput, OnlyResearchCalculationInstance
from tests.research.definition.support import definition


def external_definition(dataset_definition):  # type: ignore[no-untyped-def]
    """Use the external Indicator in the ordinary P8 scientific surface."""

    base = definition(dataset_definition)
    external = OnlyResearchCalculationInstance(
        "rsi",
        OnlyCalculationTypeReference(
            OnlyCalculationKind.INDICATOR,
            EXTERNAL_IDENTITY.type_id,
            EXTERNAL_IDENTITY.semantic_version,
        ),
        {},
        ("value",),
        (OnlyResearchCalculationInput("value", "bar.close"),),
    )
    return replace(
        base,
        calculations=tuple(external if item.instance_key == "rsi" else item for item in base.calculations),
    )


__all__ = ["external_definition"]
