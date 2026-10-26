"""One immutable, exact RESEARCH batch factory for the current chart algorithms.

This owns mathematical installation/resolution only, never Source or Product permission.
"""

from __future__ import annotations

import _decimal
import decimal
import hashlib
import importlib
import platform
from collections.abc import Mapping
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.algorithm.batch import only_validate_research_output_readiness
from onlyalpha.algorithm.type_declaration import type_declaration
from onlyalpha.calculation.chart_decimal import only_chart_study_numeric_binding
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationImplementationManifest,
    OnlyCalculationImplementationResource,
    OnlyCalculationSemanticDependency,
)
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha_plugin_indicators import definitions
from onlyalpha_plugin_indicators.chart import chart_support
from onlyalpha_plugin_indicators.research import OnlyOfficialResearchIndicatorBackend

# Current mathematical semantics: legacy RSI/ATR/MACD/VWAP/Stochastic variants are
# retained in exact historical artifacts, not silently selected for current queries.
_CURRENT = tuple(
    item for item in definitions.TYPES if item.type_id.rsplit(".", 1)[-1] not in {"rsi", "atr", "macd"}
) + (definitions.WMA, definitions.ROC, definitions.OBV, *definitions.CALIBRATED_TYPES)
_RESOURCES = (
    "onlyalpha.canonical",
    "onlyalpha.calculation.definition",
    "onlyalpha.calculation.implementation",
    "onlyalpha.calculation.decimal_execution",
    "onlyalpha.calculation.chart_decimal",
    "onlyalpha.calculation.chart_study",
    "onlyalpha.algorithm.batch",
    "onlyalpha.algorithm.codec",
    "onlyalpha.algorithm.type_declaration",
    "onlyalpha_plugin_indicators.definitions",
    "onlyalpha_plugin_indicators.chart",
    "onlyalpha_plugin_indicators.research",
    "onlyalpha_plugin_indicators.calibrated",
    "onlyalpha_plugin_indicators.financial_semantics",
    "onlyalpha_plugin_indicators.chart_factory",
)


class ChartFactory:
    """Actual retained type/resolver/backend occurrences for this installed closure."""

    def __init__(self) -> None:
        self._backend = OnlyOfficialResearchIndicatorBackend()
        self._entries = {}
        resources = {}
        for name in _RESOURCES:
            filename = importlib.import_module(name).__file__
            if filename is None:
                raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
            resources[name] = hashlib.sha256(Path(filename).read_bytes()).hexdigest()
        self.artifact = only_canonical_fingerprint(
            {
                "resources": resources,
                "pyarrow": version("pyarrow"),
                "sdk_version": version("onlyalpha"),
                "python": platform.python_version(),
                "decimal_module": hashlib.sha256(Path(decimal.__file__).read_bytes()).hexdigest(),
                "decimal_native": hashlib.sha256(Path(_decimal.__file__).read_bytes()).hexdigest(),
            }
        )
        for item in _CURRENT:
            support = chart_support(item)
            if support is None:
                raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
            resolver = (
                definitions.OnlyCalibratedDefinitionResolver(item)
                if item in definitions.CALIBRATED_TYPES
                else definitions.OnlyFinancialIndicatorDefinitionResolver(item)
                if item in definitions.FINANCIAL_TYPES
                else definitions.OnlyOfficialIndicatorDefinitionResolver(item)
            )
            implementation = OnlyCalculationImplementationManifest(
                OnlyCalculationTypeReference(item.kind, item.type_id, item.semantic_version),
                OnlyCalculationBackendKind.RESEARCH,
                "onlyalpha_plugin_indicators.chart_factory:ChartFactory",
                tuple(
                    OnlyCalculationImplementationResource(name.replace(".", "/") + ".py", digest)
                    for name, digest in resources.items()
                ),
                (OnlyCalculationSemanticDependency("onlyalpha.algorithm-sdk", "1", self.artifact),),
            )
            self._entries[(item.type_id, item.semantic_version)] = (item, resolver, support, implementation)

    def catalog(self) -> list[dict[str, object]]:
        return [
            dict(
                type_declaration(item),
                implementation_fingerprint=implementation.implementation_fingerprint,
                implementation=implementation.to_dict(),
                artifact_fingerprint=self.artifact,
                support=only_canonical_payload(support.to_dict()),
                numeric_binding=only_chart_study_numeric_binding(item.numeric),
            )
            for item, _, support, implementation in self._entries.values()
        ]

    def resolve(
        self, type_id: str, semantic_version: str, parameters: Mapping[str, object]
    ) -> OnlyCalculationDefinition:
        item, resolver, _, _ = self._entries[(type_id, semantic_version)]
        if len(parameters) > 16 or any(type(value) is int and not 0 <= value <= 10000 for value in parameters.values()):
            raise ValueError("CHART_STUDY_REQUEST_INVALID")
        definition = resolver.resolve(parameters, {})
        if (
            definition.type_id != item.type_id
            or definition.semantic_version != item.semantic_version
            or definition.inputs != item.inputs
            or definition.outputs != item.outputs
        ):
            raise ValueError("CHART_STUDY_IMPLEMENTATION_UNAVAILABLE")
        if definition.parameters.get("price_field", "CLOSE") != "CLOSE":
            raise ValueError("CHART_STUDY_REQUEST_INVALID")
        self._backend.require_chart_numeric_binding(definition.numeric)
        return definition

    def execute(
        self,
        type_id: str,
        semantic_version: str,
        parameters: Mapping[str, object],
        inputs: Mapping[str, list[object]],
        implementation: str,
    ) -> dict[str, object]:
        item, _, _, expected = self._entries[(type_id, semantic_version)]
        if implementation != expected.implementation_fingerprint:
            raise ValueError("CHART_STUDY_REGISTRATION_CHANGED")
        definition = self.resolve(type_id, semantic_version, parameters)
        if set(inputs) != {port.name for port in definition.inputs} or len({len(v) for v in inputs.values()}) != 1:
            raise ValueError("CHART_STUDY_INPUT_INVALID")
        count = len(next(iter(inputs.values())))
        if not 1 <= count <= 2001:
            raise ValueError("CHART_STUDY_CAPACITY_EXCEEDED")
        arrays = {}
        for port in item.inputs:
            values = inputs[port.name]
            if port.data_type is OnlyCalculationDataType.INTEGER:
                if any(type(value) is not int for value in values):
                    raise ValueError("CHART_STUDY_INPUT_INVALID")
                arrays[port.name] = pa.array(values, type=pa.int64())
            else:
                if any(
                    value is not None and (type(value) is not str or not Decimal(value).is_finite() or len(value) > 128)
                    for value in values
                ):
                    raise ValueError("CHART_STUDY_INPUT_INVALID")
                arrays[port.name] = pa.array(
                    [None if value is None else Decimal(cast(str, value)) for value in values],
                    type=pa.decimal128(38, 12),
                )
        execution = self._backend.execute_chart_study(definition, arrays)
        only_validate_research_output_readiness(definition, execution.outputs, execution.readiness, row_count=count)
        outputs = {
            name: {
                "values": [
                    None if value is None else format(value, "f") if isinstance(value, Decimal) else str(value)
                    for value in column.to_pylist()
                ],
                "states": execution.readiness[name].states.to_pylist(),
                "reasons": execution.readiness[name].reasons.to_pylist(),
            }
            for name, column in execution.outputs.items()
        }
        return {
            "definition": dict(definition.to_dict()),
            "definition_fingerprint": definition.fingerprint,
            "type_declaration": type_declaration(item),
            "implementation_fingerprint": expected.implementation_fingerprint,
            "artifact_fingerprint": self.artifact,
            "outputs": outputs,
        }
