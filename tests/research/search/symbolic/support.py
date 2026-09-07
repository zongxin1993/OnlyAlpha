from __future__ import annotations

from decimal import Decimal

from onlyalpha_example_alpha.provider import quant_asset_provider as factor_provider
from onlyalpha_plugin_indicators.provider import quant_asset_provider as indicator_provider
from onlyalpha_plugin_operators.provider import quant_asset_provider as operator_provider

from onlyalpha.calculation import (
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyCalculationTypeReference,
    OnlyOutputDefinition,
)
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.research.search.symbolic import (
    OnlySymbolicCandidateOutputContractV1,
    OnlySymbolicComplexityConstraintsV1,
    OnlySymbolicComponentInstanceV1,
    OnlySymbolicExternalSourceTerminalV1,
    OnlySymbolicFactorSearchSpaceV1,
)


def catalog(*, reverse: bool = False) -> OnlyQuantAssetCatalogGeneration:
    providers = (operator_provider(), indicator_provider(), factor_provider())
    return OnlyQuantAssetCatalogGeneration(tuple(reversed(providers)) if reverse else providers)


def _component(
    generation: OnlyQuantAssetCatalogGeneration,
    kind: OnlyCalculationKind,
    type_id: str,
    parameters: dict[str, object],
) -> OnlySymbolicComponentInstanceV1:
    registry = generation.calculation_registry()
    definitions = [item for item in registry.type_definitions() if item.kind is kind and item.type_id == type_id]
    assert len(definitions) == 1
    definition = definitions[0]
    return OnlySymbolicComponentInstanceV1(
        OnlyCalculationTypeReference(kind, type_id, definition.semantic_version),
        definition.parameters.normalize(parameters),
    )


def space(
    *,
    reverse: bool = False,
    max_nodes: int = 3,
    max_depth: int = 3,
    max_occurrences: int = 2,
) -> tuple[OnlyQuantAssetCatalogGeneration, OnlySymbolicFactorSearchSpaceV1]:
    generation = catalog(reverse=reverse)
    operator = _component(generation, OnlyCalculationKind.INDICATOR, "onlyalpha.operator.abs", {})
    indicator = _component(
        generation,
        OnlyCalculationKind.INDICATOR,
        "onlyalpha.indicator.rolling_return",
        {"period": 2},
    )
    bridge = _component(generation, OnlyCalculationKind.FACTOR, "example.factor.momentum", {})
    terminal = OnlySymbolicExternalSourceTerminalV1(
        "bar.close",
        OnlyOutputDefinition(
            "value",
            OnlyCalculationDataType.DECIMAL,
            True,
            ("TIME",),
            "NUMERIC_SERIES",
        ),
    )
    return generation, OnlySymbolicFactorSearchSpaceV1(
        generation.generation_fingerprint,
        (bridge, indicator, operator) if reverse else (operator, indicator, bridge),
        (terminal,),
        OnlySymbolicCandidateOutputContractV1(bridge.component_instance_fingerprint, "factor_value"),
        OnlySymbolicComplexityConstraintsV1(max_nodes, max_depth, max_occurrences),
    )


def scalar_parameters() -> dict[str, object]:
    return {"short_weight": Decimal("0.5"), "long_weight": Decimal("0.5")}
