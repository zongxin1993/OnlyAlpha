"""Canonical definitions and factories for existing trading Indicators."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from onlyalpha.application.chart_study_manifest import only_chart_study_invocation_dependency
from onlyalpha.calculation.decimal_execution import only_decimal_execution_semantic_dependency
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDefinition,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationImplementationManifest,
    OnlyCalculationStateCapability,
    only_chart_study_numeric_dependency,
    only_distribution_semantic_dependency,
    only_python_implementation_manifest,
    only_python_stdlib_semantic_dependency,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.identifiers import (
    ATR,
    BOLLINGER,
    EMA,
    MACD,
    ROLLING_RETURN,
    ROLLING_VOLATILITY,
    RSI,
    SMA,
    ZSCORE,
    OnlyIndicatorId,
    OnlyIndicatorTypeId,
)
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot
from onlyalpha_plugin_indicators.calibrated import OnlyCalibratedTradingFactory
from onlyalpha_plugin_indicators.definitions import (
    ATR_V2,
    CALIBRATED_TYPES,
    FINANCIAL_TYPES,
    TYPES,
    OnlyCalibratedDefinitionResolver,
    OnlyFinancialIndicatorDefinitionResolver,
    OnlyOfficialIndicatorDefinitionResolver,
    resolve_definition,
)
from onlyalpha_plugin_indicators.definitions import (
    ATR_V3 as ATR_V3,
)
from onlyalpha_plugin_indicators.definitions import (
    MACD_V2 as MACD_V2,
)
from onlyalpha_plugin_indicators.definitions import (
    OBV as OBV,
)
from onlyalpha_plugin_indicators.definitions import (
    ROC as ROC,
)
from onlyalpha_plugin_indicators.definitions import (
    RSI_V2 as RSI_V2,
)
from onlyalpha_plugin_indicators.definitions import (
    STOCHASTIC as STOCHASTIC,
)
from onlyalpha_plugin_indicators.definitions import (
    STOCHASTIC_V2 as STOCHASTIC_V2,
)
from onlyalpha_plugin_indicators.definitions import (
    VALUE as VALUE,
)
from onlyalpha_plugin_indicators.definitions import (
    VWAP as VWAP,
)
from onlyalpha_plugin_indicators.definitions import (
    VWAP_V2 as VWAP_V2,
)
from onlyalpha_plugin_indicators.definitions import (
    WMA as WMA,
)
from onlyalpha_plugin_indicators.definitions import (
    warmup as warmup,
)
from onlyalpha_plugin_indicators.financial import OnlyFinancialTradingBackendFactory
from onlyalpha_plugin_indicators.macd import OnlyMacdIndicator, config_from_parameters
from onlyalpha_plugin_indicators.research import OnlyOfficialResearchIndicatorBackend
from onlyalpha_plugin_indicators.standard import OnlyRollingIndicatorConfig, OnlyStandardBarIndicator


@dataclass(frozen=True, slots=True)
class OnlyIndicatorBackendRequest:
    indicator_id: OnlyIndicatorId
    bar_type: OnlyBarType


class OnlyStandardBackendFactory:
    def __init__(self, type_definition: OnlyCalculationTypeDefinition) -> None:
        self.type_definition = type_definition

    @property
    def indicator_type(self) -> OnlyIndicatorTypeId:
        return _legacy_type(self.type_definition.type_id)

    def resolve_definition(self, parameters: Mapping[str, object]) -> OnlyCalculationDefinition:
        return resolve_definition(self.type_definition, dict(parameters))

    def create(self, definition: OnlyCalculationDefinition, request: object) -> OnlyBarIndicator[OnlyIndicatorSnapshot]:
        if not hasattr(request, "indicator_id") or not hasattr(request, "bar_type"):
            raise TypeError("Indicator backend requires an Indicator request")
        p = definition.parameters
        result = OnlyStandardBarIndicator(
            OnlyRollingIndicatorConfig(
                request.indicator_id,
                request.bar_type,
                int(str(p["period"])),
                str(p["price_field"]),
                Decimal(str(p.get("standard_deviations", "2"))),
            ),
            _legacy_type(definition.type_id),
        )
        result.bind_definition(definition)
        return result


class OnlyMacdBackendFactory:
    def __init__(self, type_definition: OnlyCalculationTypeDefinition) -> None:
        self.type_definition = type_definition

    @property
    def indicator_type(self) -> OnlyIndicatorTypeId:
        return MACD

    def resolve_definition(self, parameters: Mapping[str, object]) -> OnlyCalculationDefinition:
        return resolve_definition(self.type_definition, dict(parameters))

    def create(self, definition: OnlyCalculationDefinition, request: object) -> OnlyMacdIndicator:
        if not hasattr(request, "indicator_id") or not hasattr(request, "bar_type"):
            raise TypeError("Indicator backend requires an Indicator request")
        return OnlyMacdIndicator(
            config_from_parameters(request.indicator_id, request.bar_type, definition.parameters), definition
        )


def _legacy_type(type_id: str) -> OnlyIndicatorTypeId:
    return {
        "onlyalpha.indicator.ema": EMA,
        "onlyalpha.indicator.sma": SMA,
        "onlyalpha.indicator.rsi": RSI,
        "onlyalpha.indicator.atr": ATR,
        "onlyalpha.indicator.bollinger": BOLLINGER,
        "onlyalpha.indicator.rolling_return": ROLLING_RETURN,
        "onlyalpha.indicator.rolling_volatility": ROLLING_VOLATILITY,
        "onlyalpha.indicator.zscore": ZSCORE,
    }[type_id]


def registrations() -> tuple[OnlyCalculationBackendRegistration, ...]:
    resolvers = tuple(OnlyOfficialIndicatorDefinitionResolver(item) for item in (*TYPES, ATR_V2))
    financial_resolvers = tuple(OnlyFinancialIndicatorDefinitionResolver(item) for item in FINANCIAL_TYPES)

    def resolver_for(item: OnlyCalculationTypeDefinition) -> OnlyOfficialIndicatorDefinitionResolver:
        return next(resolver for resolver in resolvers if resolver.type_definition is item)

    package_root = Path(__file__).resolve().parent

    def manifest(
        item: OnlyCalculationTypeDefinition,
        backend: OnlyCalculationBackendKind,
        entrypoint: str,
        resources: tuple[str, ...],
    ) -> OnlyCalculationImplementationManifest:
        return only_python_implementation_manifest(
            calculation_type_reference=OnlyCalculationTypeReference(item.kind, item.type_id, item.semantic_version),
            backend_kind=backend,
            entrypoint_identity=entrypoint,
            package_root=package_root,
            resource_paths=resources,
            semantic_dependencies=(
                *(
                    (only_decimal_execution_semantic_dependency(),)
                    if backend is OnlyCalculationBackendKind.TRADING and item in (*FINANCIAL_TYPES, *CALIBRATED_TYPES)
                    else ()
                ),
                *(
                    (
                        only_decimal_execution_semantic_dependency(),
                        only_chart_study_numeric_dependency(),
                        only_chart_study_invocation_dependency(),
                    )
                    if backend is OnlyCalculationBackendKind.RESEARCH
                    else ()
                ),
                only_python_stdlib_semantic_dependency("decimal"),
                *(
                    (only_distribution_semantic_dependency("pyarrow"),)
                    if backend is OnlyCalculationBackendKind.RESEARCH
                    else ()
                ),
            ),
        )

    trading = tuple(
        OnlyCalculationBackendRegistration(
            item,
            OnlyCalculationBackendKind.TRADING,
            OnlyMacdBackendFactory(item) if item.type_id.endswith(".macd") else OnlyStandardBackendFactory(item),
            resolver_for(item),
            manifest(
                item,
                OnlyCalculationBackendKind.TRADING,
                (
                    "onlyalpha_plugin_indicators.registration:OnlyMacdBackendFactory"
                    if item.type_id.endswith(".macd")
                    else "onlyalpha_plugin_indicators.registration:OnlyStandardBackendFactory"
                ),
                (
                    ("registration.py", "definitions.py", "macd.py", "snapshots.py")
                    if item.type_id.endswith(".macd")
                    else ("registration.py", "definitions.py", "standard.py", "snapshots.py")
                ),
            ),
            OnlyCalculationStateCapability.CHECKPOINTABLE,
            1,
        )
        for item in (*TYPES, ATR_V2)
    )
    research = tuple(
        OnlyCalculationBackendRegistration(
            item,
            OnlyCalculationBackendKind.RESEARCH,
            OnlyOfficialResearchIndicatorBackend(),
            resolver_for(item),
            manifest(
                item,
                OnlyCalculationBackendKind.RESEARCH,
                "onlyalpha_plugin_indicators.research:OnlyOfficialResearchIndicatorBackend",
                (
                    "registration.py",
                    "definitions.py",
                    "research.py",
                    "provider.py",
                    "chart.py",
                    "calibrated.py",
                    "financial_semantics.py",
                ),
            ),
            readiness_contract_versions=(1,)
            if item.type_id == "onlyalpha.indicator.sma" and item.semantic_version == "1"
            else (),
        )
        for item in (*TYPES[:3], *TYPES[4:], ATR_V2)
    )
    financial_trading = tuple(
        OnlyCalculationBackendRegistration(
            item,
            OnlyCalculationBackendKind.TRADING,
            OnlyFinancialTradingBackendFactory(),
            next(resolver for resolver in financial_resolvers if resolver.type_definition is item),
            manifest(
                item,
                OnlyCalculationBackendKind.TRADING,
                "onlyalpha_plugin_indicators.financial:OnlyFinancialTradingBackendFactory",
                ("registration.py", "definitions.py", "financial.py", "financial_semantics.py"),
            ),
            OnlyCalculationStateCapability.CHECKPOINTABLE,
            1,
        )
        for item in FINANCIAL_TYPES
    )
    financial_research = tuple(
        OnlyCalculationBackendRegistration(
            item,
            OnlyCalculationBackendKind.RESEARCH,
            OnlyOfficialResearchIndicatorBackend(),
            next(resolver for resolver in financial_resolvers if resolver.type_definition is item),
            manifest(
                item,
                OnlyCalculationBackendKind.RESEARCH,
                "onlyalpha_plugin_indicators.research:OnlyOfficialResearchIndicatorBackend",
                (
                    "registration.py",
                    "definitions.py",
                    "research.py",
                    "financial_semantics.py",
                    "chart.py",
                    "calibrated.py",
                    "provider.py",
                ),
            ),
        )
        for item in FINANCIAL_TYPES
    )
    calibrated = tuple(
        OnlyCalculationBackendRegistration(
            item,
            backend,
            OnlyCalibratedTradingFactory()
            if backend is OnlyCalculationBackendKind.TRADING
            else OnlyOfficialResearchIndicatorBackend(),
            OnlyCalibratedDefinitionResolver(item),
            manifest(
                item,
                backend,
                "onlyalpha_plugin_indicators.calibrated:OnlyCalibratedTradingFactory"
                if backend is OnlyCalculationBackendKind.TRADING
                else "onlyalpha_plugin_indicators.research:OnlyOfficialResearchIndicatorBackend",
                (
                    "registration.py",
                    "definitions.py",
                    "calibrated.py",
                    "financial_semantics.py",
                    "research.py",
                    "chart.py",
                    "provider.py",
                ),
            ),
            OnlyCalculationStateCapability.CHECKPOINTABLE if backend is OnlyCalculationBackendKind.TRADING else None,
            1 if backend is OnlyCalculationBackendKind.TRADING else None,
        )
        for item in CALIBRATED_TYPES
        for backend in (OnlyCalculationBackendKind.TRADING, OnlyCalculationBackendKind.RESEARCH)
    )
    return trading + research + financial_trading + financial_research + calibrated
