"""Official system-owned actual-backend Calculation Equivalence Certification V2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.equivalence import (
    OnlyCalculationEquivalenceCertificationProfile,
    OnlyCalculationEquivalenceError,
    OnlyCalculationEquivalenceEvidenceV2,
    OnlyCalculationEquivalenceEvidenceV2Store,
    _only_seal_certified_equivalence,
    only_calculation_equivalence_comparison_fingerprint,
    only_required_calculation_equivalence_profile,
)
from onlyalpha.calculation.graph import OnlyCalculationNodeDefinition
from onlyalpha.calculation.registry import (
    OnlyCalculationBackendRegistration,
    OnlyCalculationRegistry,
    OnlyTradingBackendFactory,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.indicator.identifiers import OnlyIndicatorId
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackend
from onlyalpha.strategy.execution import only_invoke_trading_calculation

_CONTRACT = "P9_CALCULATION_EQUIVALENCE_V2"
_DECIMAL = pa.decimal128(38, 12)


@dataclass(frozen=True, slots=True)
class _CertificationRequest:
    indicator_id: OnlyIndicatorId
    bar_type: OnlyBarType


@dataclass(frozen=True, slots=True)
class _CorpusCase:
    case_id: str
    bars: tuple[OnlyBar, ...]
    inputs: Mapping[str, pa.Array]


@dataclass(frozen=True, slots=True)
class _CertificationHorizon:
    """Exact-node state boundary exercised by the system-owned corpus."""

    minimum_observations: int
    observation_count: int
    state_model: str

    def __post_init__(self) -> None:
        if self.minimum_observations <= 0 or self.observation_count <= self.minimum_observations:
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_CERTIFICATION_HORIZON_INVALID", self.state_model)


class OnlyCalculationEquivalenceCertificationProfileAuthority:
    """Closed P9.0 profile selection; callers cannot supply profiles or corpora."""

    def resolve(self, definition: OnlyCalculationDefinition) -> OnlyCalculationEquivalenceCertificationProfile:
        return only_required_calculation_equivalence_profile(definition)


class OnlyCalculationEquivalenceCertificationApplicationService:
    """The only production authority allowed to mint admission-grade Evidence V2."""

    def __init__(
        self,
        calculations: OnlyCalculationRegistry,
        evidence_store: OnlyCalculationEquivalenceEvidenceV2Store,
    ) -> None:
        self._calculations = calculations
        self._evidence_store = evidence_store
        self._profiles = OnlyCalculationEquivalenceCertificationProfileAuthority()

    def certify(self, node: OnlyCalculationNodeDefinition) -> OnlyCalculationEquivalenceEvidenceV2:
        if not isinstance(node, OnlyCalculationNodeDefinition):
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_CERTIFICATION_FAILED", "certification requires an exact Calculation node"
            )
        definition = node.definition
        reference = OnlyCalculationTypeReference(definition.kind, definition.type_id, definition.semantic_version)
        research = self._registration(reference, OnlyCalculationBackendKind.RESEARCH)
        trading = self._registration(reference, OnlyCalculationBackendKind.TRADING)
        if research.implementation_manifest is None or trading.implementation_manifest is None:
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_CERTIFICATION_FAILED", "exact implementation manifest is unavailable"
            )
        profile = self._profiles.resolve(definition)
        corpus = _materialize_corpus(definition, profile)
        corpus_fingerprint = only_canonical_fingerprint(
            {
                "domain": "onlyalpha.calculation.equivalence-corpus",
                "schema_version": 2,
                "calculation_node_fingerprint": node.fingerprint,
                "certification_profile_fingerprint": profile.profile_fingerprint,
                "cases": [_case_payload(item) for item in corpus],
            }
        )
        try:
            research_rows = _execute_research(definition, research, corpus)
            trading_rows = _execute_trading(definition, trading, corpus)
        except OnlyCalculationEquivalenceError:
            raise
        except Exception as exc:
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_CERTIFICATION_FAILED",
                f"actual backend execution failed: {type(exc).__name__}",
            ) from exc
        research_output = _output_fingerprint(node.fingerprint, research_rows)
        trading_output = _output_fingerprint(node.fingerprint, trading_rows)
        if research_rows != trading_rows or research_output != trading_output:
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_CERTIFICATION_FAILED",
                f"exact outputs differ for {definition.type_id}@{definition.semantic_version}",
            )
        research_fingerprint = research.implementation_manifest.implementation_fingerprint
        trading_fingerprint = trading.implementation_manifest.implementation_fingerprint
        comparison = only_calculation_equivalence_comparison_fingerprint(
            calculation_node_fingerprint=node.fingerprint,
            research_implementation_fingerprint=research_fingerprint,
            trading_implementation_fingerprint=trading_fingerprint,
            equivalence_contract_version=_CONTRACT,
            certification_profile_fingerprint=profile.profile_fingerprint,
            corpus_fingerprint=corpus_fingerprint,
            research_output_fingerprint=research_output,
            trading_output_fingerprint=trading_output,
        )
        evidence = OnlyCalculationEquivalenceEvidenceV2(
            node.fingerprint,
            reference,
            research_fingerprint,
            trading_fingerprint,
            _CONTRACT,
            profile.profile_id,
            profile.profile_fingerprint,
            corpus_fingerprint,
            research_output,
            trading_output,
            comparison,
        )
        return self._evidence_store.publish_certified(_only_seal_certified_equivalence(evidence))

    def _registration(
        self, reference: OnlyCalculationTypeReference, backend: OnlyCalculationBackendKind
    ) -> OnlyCalculationBackendRegistration:
        try:
            return self._calculations.resolve(reference.kind, reference.type_id, reference.semantic_version, backend)
        except ValueError as exc:
            raise OnlyCalculationEquivalenceError(
                "EQUIVALENCE_CERTIFICATION_FAILED", f"{backend.value} backend is unavailable"
            ) from exc


def _materialize_corpus(
    definition: OnlyCalculationDefinition,
    profile: OnlyCalculationEquivalenceCertificationProfile,
) -> tuple[_CorpusCase, ...]:
    horizon = _required_certification_horizon(definition)
    result: list[_CorpusCase] = []
    for ordinal, case_id in enumerate(profile.cases):
        values = _decimal_values(case_id, horizon.observation_count)
        bars = _bars(case_id, ordinal, values)
        inputs: dict[str, pa.Array] = {}
        contracts = {item.name: item for item in definition.inputs}
        for name in sorted(definition.input_bindings):
            contract = contracts[name]
            source = definition.input_bindings[name].source
            raw = (
                _source_values(source, bars)
                if source is not None
                else _contract_values(contract.data_type, case_id, horizon.observation_count)
            )
            if contract.nullable and case_id in {"NULLABLE_INPUT_SEMANTICS", "BOOLEAN_TRUTH_NULL_SEMANTICS"}:
                raw = tuple(None if index in {1, 4} else value for index, value in enumerate(raw))
            inputs[name] = _array(contract.data_type, raw)
        result.append(_CorpusCase(case_id, bars, MappingProxyType(inputs)))
    return tuple(result)


def _required_certification_horizon(definition: OnlyCalculationDefinition) -> _CertificationHorizon:
    """Derive the finite engineering horizon from exact resolved semantics.

    This is deterministic admission evidence, not a mathematical proof over all inputs.
    """

    minimum = definition.warmup.minimum_observations
    initialization = definition.warmup.initialization.upper()
    type_id = definition.type_id
    parameters = definition.parameters
    declared_periods = tuple(
        int(str(parameters[name]))
        for name in ("period", "fast_period", "slow_period", "signal_period", "warmup_bars")
        if name in parameters
    )
    if declared_periods and any(value <= 0 for value in declared_periods):
        raise OnlyCalculationEquivalenceError("EQUIVALENCE_CERTIFICATION_HORIZON_INVALID", type_id)
    if type_id.endswith(".macd"):
        warmup = int(str(parameters.get("warmup_bars", minimum)))
        slow = int(str(parameters.get("slow_period", warmup)))
        signal = int(str(parameters.get("signal_period", 1)))
        boundary = max(minimum, warmup, slow + signal - 1)
        return _CertificationHorizon(boundary, boundary + max(4, signal), "MACD_RECURSIVE")
    if "EMA" in initialization or type_id.endswith(".ema"):
        period = int(str(parameters.get("period", minimum)))
        boundary = max(minimum, period)
        return _CertificationHorizon(boundary, boundary + max(4, period), "RECURSIVE")
    if "WINDOW" in initialization or "period" in parameters:
        period = int(str(parameters.get("period", minimum)))
        boundary = max(minimum, period)
        # first full window, first eviction, then two post-eviction steady observations
        return _CertificationHorizon(boundary, boundary + 3, "ROLLING_WINDOW")
    return _CertificationHorizon(minimum, max(minimum + 3, 8), "STATE_TRANSITION")


def _execute_research(
    definition: OnlyCalculationDefinition,
    registration: OnlyCalculationBackendRegistration,
    corpus: tuple[_CorpusCase, ...],
) -> tuple[tuple[str, int, tuple[tuple[str, object], ...]], ...]:
    provider = registration.provider
    if not callable(getattr(provider, "execute", None)):
        raise OnlyCalculationEquivalenceError("EQUIVALENCE_CERTIFICATION_FAILED", "RESEARCH backend is invalid")
    backend = cast(OnlyResearchCalculationBackend, provider)
    rows: list[tuple[str, int, tuple[tuple[str, object], ...]]] = []
    for case in corpus:
        outputs = backend.execute(definition, case.inputs)
        if set(outputs) != {item.name for item in definition.outputs}:
            raise OnlyCalculationEquivalenceError("EQUIVALENCE_CERTIFICATION_FAILED", "RESEARCH output names differ")
        for index in range(len(case.bars)):
            rows.append(
                (
                    case.case_id,
                    index,
                    tuple((name, outputs[name][index].as_py()) for name in sorted(outputs)),
                )
            )
    return tuple(rows)


def _execute_trading(
    definition: OnlyCalculationDefinition,
    registration: OnlyCalculationBackendRegistration,
    corpus: tuple[_CorpusCase, ...],
) -> tuple[tuple[str, int, tuple[tuple[str, object], ...]], ...]:
    provider = registration.provider
    if not callable(getattr(provider, "create", None)):
        raise OnlyCalculationEquivalenceError("EQUIVALENCE_CERTIFICATION_FAILED", "TRADING backend is invalid")
    factory = cast(OnlyTradingBackendFactory, provider)
    rows: list[tuple[str, int, tuple[tuple[str, object], ...]]] = []
    for case in corpus:
        request = _CertificationRequest(
            OnlyIndicatorId(f"cert-{only_canonical_fingerprint(case.case_id)[:24]}"),
            case.bars[0].bar_type,
        )
        instance = factory.create(definition, request)
        for index, bar in enumerate(case.bars):
            inputs = {name: value[index].as_py() for name, value in case.inputs.items()}
            outputs = only_invoke_trading_calculation(instance, definition.outputs, bar, inputs)
            if set(outputs) != {item.name for item in definition.outputs}:
                raise OnlyCalculationEquivalenceError("EQUIVALENCE_CERTIFICATION_FAILED", "TRADING output names differ")
            rows.append(
                (
                    case.case_id,
                    index,
                    tuple((name, _plain(outputs[name])) for name in sorted(outputs)),
                )
            )
    return tuple(rows)


def _output_fingerprint(
    node_fingerprint: str,
    rows: tuple[tuple[str, int, tuple[tuple[str, object], ...]], ...],
) -> str:
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.calculation.equivalence-output",
            "schema_version": 2,
            "calculation_node_fingerprint": node_fingerprint,
            "rows": [
                {
                    "case_id": case_id,
                    "ordinal": ordinal,
                    "outputs": {name: _typed(value) for name, value in outputs},
                }
                for case_id, ordinal, outputs in rows
            ],
        }
    )


def _case_payload(case: _CorpusCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "inputs": {
            name: [_typed(value) for value in values.to_pylist()] for name, values in sorted(case.inputs.items())
        },
        "bars": [
            {
                "open": _typed(bar.open.value),
                "high": _typed(bar.high.value),
                "low": _typed(bar.low.value),
                "close": _typed(bar.close.value),
                "volume": _typed(bar.volume.value),
                "bar_end": bar.bar_end,
            }
            for bar in case.bars
        ],
    }


def _decimal_values(case_id: str, count: int) -> tuple[Decimal, ...]:
    if count <= 0:
        raise OnlyCalculationEquivalenceError("EQUIVALENCE_CERTIFICATION_HORIZON_INVALID", case_id)
    if case_id == "FLAT_SEQUENCE":
        return (Decimal("10"),) * count
    if case_id == "NEGATIVE_SLOPE_SEQUENCE":
        return tuple(Decimal(2 * (count - index)) for index in range(count))
    if case_id == "POSITIVE_SLOPE_SEQUENCE":
        return tuple(Decimal(2 * (index + 1)) for index in range(count))
    if case_id == "QUANTIZATION_BOUNDARY":
        quantum = Decimal("0.000000000001")
        return tuple(Decimal("1") + quantum * index for index in range(count))
    if case_id == "WARMUP_AND_STEADY_STATE":
        return tuple(Decimal(index + 1) ** 2 for index in range(count))
    seeds = {
        "ZERO_BOUNDARY": ("0", "0", "1", "0", "2", "0"),
        "NULLABLE_INPUT_SEMANTICS": ("1", "2", "3", "4", "5", "6"),
        "BOOLEAN_TRUTH_NULL_SEMANTICS": ("1", "2", "3", "4", "5", "6"),
        "MULTI_OUTPUT_ALIGNMENT": ("3", "1", "4", "1", "5", "9"),
    }
    seed = tuple(Decimal(item) for item in seeds[case_id])
    return tuple(seed[index % len(seed)] + Decimal(index // len(seed)) for index in range(count))


def _contract_values(data_type: OnlyCalculationDataType, case_id: str, count: int) -> tuple[object, ...]:
    values = _decimal_values(case_id, count)
    if data_type is OnlyCalculationDataType.DECIMAL:
        return tuple(value - Decimal("3") for value in values)
    if data_type is OnlyCalculationDataType.INTEGER:
        return tuple(int(value) for value in values)
    if data_type is OnlyCalculationDataType.BOOLEAN:
        return tuple(index % 2 == 0 for index in range(count))
    return tuple(f"v{index}" for index in range(count))


def _source_values(source: str | None, bars: tuple[OnlyBar, ...]) -> tuple[object, ...]:
    attributes: dict[str, tuple[object, ...]] = {
        "bar.open": tuple(item.open.value for item in bars),
        "bar.high": tuple(item.high.value for item in bars),
        "bar.low": tuple(item.low.value for item in bars),
        "bar.close": tuple(item.close.value for item in bars),
        "bar.volume": tuple(item.volume.value for item in bars),
        "bar.quote_volume": tuple(None if item.quote_volume is None else item.quote_volume.value for item in bars),
        "bar.turnover": tuple(None if item.turnover is None else item.turnover.amount for item in bars),
        "bar.trade_count": tuple(item.trade_count for item in bars),
        "bar.open_interest": tuple(None if item.open_interest is None else item.open_interest.value for item in bars),
    }
    try:
        return attributes[str(source)]
    except KeyError as exc:
        raise OnlyCalculationEquivalenceError(
            "EQUIVALENCE_CERTIFICATION_PROFILE_UNAVAILABLE", f"unsupported source {source}"
        ) from exc


def _array(data_type: OnlyCalculationDataType, values: tuple[object, ...]) -> pa.Array:
    arrow_type: pa.DataType = {
        OnlyCalculationDataType.DECIMAL: _DECIMAL,
        OnlyCalculationDataType.INTEGER: pa.int64(),
        OnlyCalculationDataType.BOOLEAN: pa.bool_(),
        OnlyCalculationDataType.STRING: pa.string(),
    }[data_type]
    return pa.array(values, type=arrow_type)


def _bars(case_id: str, case_ordinal: int, values: tuple[Decimal, ...]) -> tuple[OnlyBar, ...]:
    instrument = OnlyInstrumentId.parse("CERTIFICATION.XNAS")
    bar_type = OnlyBarType(
        instrument,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    base = datetime(2026, 1, 5, 14, 30, tzinfo=UTC) + timedelta(days=case_ordinal)
    result: list[OnlyBar] = []
    for index, raw in enumerate(values):
        close = max(raw, Decimal("0"))
        start = base + timedelta(minutes=index)
        result.append(
            OnlyBar(
                bar_type=bar_type,
                open=OnlyPrice(close, 18),
                high=OnlyPrice(close + Decimal("1"), 18),
                low=OnlyPrice(max(close - Decimal("1"), Decimal("0")), 18),
                close=OnlyPrice(close, 18),
                volume=OnlyQuantity(Decimal(100 + index), 0),
                quote_volume=None,
                turnover=None,
                trade_count=index,
                open_interest=None,
                bar_start=start,
                bar_end=start + timedelta(minutes=1),
                ts_event=start + timedelta(minutes=1),
                ts_init=start + timedelta(minutes=1),
                is_closed=True,
                revision=0,
                adjustment_type=OnlyAdjustmentType.RAW,
                trading_day=date(2026, 1, 5) + timedelta(days=case_ordinal),
                session_type=OnlySessionType.CONTINUOUS,
            )
        )
    return tuple(result)


def _plain(value: object) -> object:
    return value.value if isinstance(value, Enum) else value


def _typed(value: object) -> object:
    value = _plain(value)
    if value is None:
        return {"type": "NULL", "value": None}
    if isinstance(value, bool):
        return {"type": "BOOLEAN", "value": value}
    if isinstance(value, Decimal):
        return {"type": "DECIMAL", "value": str(value)}
    if isinstance(value, int):
        return {"type": "INTEGER", "value": str(value)}
    if isinstance(value, str):
        return {"type": "STRING", "value": value}
    raise TypeError(f"unsupported equivalence value: {type(value).__name__}")


__all__ = [name for name in globals() if name.startswith("Only")]
