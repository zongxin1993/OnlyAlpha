from __future__ import annotations

from decimal import Decimal

from onlyalpha_example_alpha.registration import MOMENTUM
from onlyalpha_plugin_indicators.registration import TYPES
from onlyalpha_plugin_targets.registration import FORWARD_RETURN

from onlyalpha.calculation import OnlyCalculationDataType, OnlyCalculationKind, OnlyCalculationTypeReference
from onlyalpha.research import (
    OnlyResearchAnd,
    OnlyResearchCalculationInput,
    OnlyResearchCalculationInstance,
    OnlyResearchComparison,
    OnlyResearchComparisonOperator,
    OnlyResearchDatasetFieldRef,
    OnlyResearchDatasetSelection,
    OnlyResearchDefinition,
    OnlyResearchFixedParameter,
    OnlyResearchSignals,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticsRequest,
    OnlyResearchSweepParameter,
    OnlyResearchTypedLiteral,
    OnlyResearchUniverseKind,
    OnlyResearchUniverseSelection,
    OnlyResearchVariableRef,
)


def reference(kind: OnlyCalculationKind, type_id: str) -> OnlyCalculationTypeReference:
    return OnlyCalculationTypeReference(kind, type_id, "1")


def definition(
    dataset_definition, *, reverse_sweeps: bool = False, metadata: object = "first"
) -> OnlyResearchDefinition:
    rsi = next(item for item in TYPES if item.type_id == "onlyalpha.indicator.rsi")
    rolling = next(item for item in TYPES if item.type_id == "onlyalpha.indicator.rolling_return")
    periods = (14, 7) if reverse_sweeps else (7, 14)
    windows = (2, 1) if reverse_sweeps else (1, 2)
    calculations = (
        OnlyResearchCalculationInstance(
            "rsi",
            reference(OnlyCalculationKind.INDICATOR, rsi.type_id),
            {"period": OnlyResearchSweepParameter(periods)},
            ("value",),
        ),
        OnlyResearchCalculationInstance(
            "returns_short",
            reference(OnlyCalculationKind.INDICATOR, rolling.type_id),
            {"period": OnlyResearchSweepParameter(windows)},
            ("value",),
        ),
        OnlyResearchCalculationInstance(
            "returns_long",
            reference(OnlyCalculationKind.INDICATOR, rolling.type_id),
            {"period": OnlyResearchFixedParameter(3)},
            ("value",),
        ),
        OnlyResearchCalculationInstance(
            "momentum",
            reference(OnlyCalculationKind.FACTOR, MOMENTUM.type_id),
            {
                "short_weight": OnlyResearchFixedParameter(Decimal("0.5")),
                "long_weight": OnlyResearchFixedParameter(Decimal("0.5")),
            },
            ("factor_value",),
            (
                OnlyResearchCalculationInput("return_short", OnlyResearchVariableRef("returns_short", "value")),
                OnlyResearchCalculationInput("return_long", OnlyResearchVariableRef("returns_long", "value")),
            ),
        ),
    )
    eligibility = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchDatasetFieldRef("close"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("5")),
    )
    entry = OnlyResearchAnd(
        (
            OnlyResearchComparison(
                OnlyResearchComparisonOperator.LT,
                OnlyResearchVariableRef("rsi", "value"),
                OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("30")),
            ),
            OnlyResearchComparison(
                OnlyResearchComparisonOperator.GT,
                OnlyResearchVariableRef("momentum", "factor_value"),
                OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("0")),
            ),
        )
    )
    exit_expression = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchVariableRef("rsi", "value"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("70")),
    )
    target = OnlyResearchCalculationInstance(
        "forward_return_1",
        reference(OnlyCalculationKind.TARGET, FORWARD_RETURN.type_id),
        {"exit_offset": OnlyResearchFixedParameter(1)},
        ("target_value",),
        (
            OnlyResearchCalculationInput("entry_price", "bar.close"),
            OnlyResearchCalculationInput("exit_price", "bar.close"),
        ),
    )
    return OnlyResearchDefinition(
        OnlyResearchDatasetSelection(
            OnlyResearchUniverseSelection(
                OnlyResearchUniverseKind.EXPLICIT_INSTRUMENT_SET,
                tuple(str(item) for item in dataset_definition.instruments),
            ),
            dataset_definition.bar_specification,
            dataset_definition.aggregation_source,
            dataset_definition.time_range.start.isoformat(),
            dataset_definition.time_range.end.isoformat(),
            dataset_definition.adjustment_type,
            dataset_definition.adjustment_reference,
        ),
        calculations,
        eligibility,
        OnlyResearchSignals(entry, exit_expression),
        (target,),
        (
            OnlyResearchStatisticsRequest(
                OnlyResearchVariableRef("momentum", "factor_value"),
                "forward_return_1",
                OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC),
            ),
        ),
        display_metadata={"name": metadata, "layout": [3, 2, 1]},
    )
