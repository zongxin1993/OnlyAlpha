from decimal import Decimal

from onlyalpha_example_alpha.registration import resolve_momentum
from onlyalpha_plugin_indicators.registration import (
    ROC,
    STOCHASTIC,
    TYPES,
    VWAP,
    WMA,
    OnlyFinancialIndicatorDefinitionResolver,
    resolve_definition,
)
from onlyalpha_plugin_indicators.registration import (
    registrations as indicator_registrations,
)
from onlyalpha_plugin_operators.registration import (
    ABS,
    ADD,
    CROSS_SECTION_DEMEAN,
    CROSS_SECTION_PERCENTILE,
    CROSS_SECTION_RANK,
    CROSS_SECTION_ZSCORE,
    DECAY_LINEAR,
    DELAY,
    DELTA,
    DIVIDE,
    ROLLING_CORRELATION,
    ROLLING_COVARIANCE,
    ROLLING_MAX,
    ROLLING_MEAN,
    ROLLING_MIN,
    ROLLING_STD,
    ROLLING_VAR,
    SCALE,
    SIGN,
    SUBTRACT,
    TS_RANK,
    resolve_operator,
)
from onlyalpha_plugin_operators.registration import (
    registrations as operator_registrations,
)

from onlyalpha.calculation import (
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationReference,
    OnlyCalculationRegistry,
)
from onlyalpha.research import OnlyResearchCalculationBackendResolver, OnlyResearchCalculationExecutor
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from tests.research.calculation.support import snapshot


def _source(name: str) -> OnlyCalculationReference:
    return OnlyCalculationReference(None, name, f"bar.{name}")


def _output(definition, name: str = "value") -> OnlyCalculationReference:
    return OnlyCalculationReference(definition.fingerprint, name)


def _graph(*definitions) -> OnlyCalculationGraphDefinition:
    nodes = tuple(OnlyCalculationNodeDefinition(definition) for definition in definitions)
    graph = OnlyCalculationGraphDefinition(nodes)
    assert graph.fingerprint == OnlyCalculationGraphDefinition(tuple(reversed(nodes))).fingerprint
    return graph


def _standard(type_id: str, period: int):
    definition = next(item for item in TYPES if item.type_id == type_id)
    return resolve_definition(definition, {"period": period})


def _representative_compositions() -> dict[str, OnlyCalculationGraphDefinition]:
    close, volume = _source("close"), _source("volume")
    mean = resolve_operator(ROLLING_MEAN, {"period": 5}, value=close)
    delta_mean = resolve_operator(DELTA, {"period": 2}, value=_output(mean))

    mean20 = resolve_operator(ROLLING_MEAN, {"period": 20}, value=close)
    std20 = resolve_operator(ROLLING_STD, {"period": 20}, value=close)
    spread = resolve_operator(SUBTRACT, {}, left=close, right=_output(mean20))
    normalized = resolve_operator(DIVIDE, {}, left=_output(spread), right=_output(std20))

    covariance = resolve_operator(ROLLING_COVARIANCE, {"period": 10}, left=close, right=volume)
    absolute_covariance = resolve_operator(ABS, {}, value=_output(covariance))

    correlation = resolve_operator(ROLLING_CORRELATION, {"period": 10}, left=close, right=volume)
    ranked = resolve_operator(TS_RANK, {"period": 20}, value=_output(correlation))

    source_delta = resolve_operator(DELTA, {"period": 5}, value=close)
    decayed_delta = resolve_operator(DECAY_LINEAR, {"period": 10}, value=_output(source_delta))

    rolling_return = _standard("onlyalpha.indicator.rolling_return", 5)
    percentile = resolve_operator(CROSS_SECTION_PERCENTILE, {}, value=_output(rolling_return))

    rolling_volatility = _standard("onlyalpha.indicator.rolling_volatility", 5)
    cross_rank = resolve_operator(CROSS_SECTION_RANK, {}, value=_output(rolling_volatility))

    wma = OnlyFinancialIndicatorDefinitionResolver(WMA).resolve({"period": 20}, {"price": close})
    zscore = resolve_operator(CROSS_SECTION_ZSCORE, {}, value=_output(wma))

    roc = OnlyFinancialIndicatorDefinitionResolver(ROC).resolve({"period": 5}, {"price": close})
    demeaned = resolve_operator(CROSS_SECTION_DEMEAN, {}, value=_output(roc, "roc"))

    wma_short = OnlyFinancialIndicatorDefinitionResolver(WMA).resolve({"period": 5}, {"price": close})
    wma_delta = resolve_operator(DELTA, {"period": 2}, value=_output(wma_short))

    absolute_roc = resolve_operator(ABS, {}, value=_output(roc, "roc"))

    vwap = OnlyFinancialIndicatorDefinitionResolver(VWAP).resolve({"period": 5}, {"price": close, "volume": volume})
    vwap_delta = resolve_operator(DELTA, {"period": 2}, value=_output(vwap, "vwap"))

    stochastic = OnlyFinancialIndicatorDefinitionResolver(STOCHASTIC).resolve(
        {"k_period": 3, "d_period": 2},
        {"high": _source("high"), "low": _source("low"), "close": close},
    )
    stochastic_rank = resolve_operator(TS_RANK, {"period": 2}, value=_output(stochastic, "k"))

    short_return = _standard("onlyalpha.indicator.rolling_return", 1)
    long_return = _standard("onlyalpha.indicator.rolling_return", 2)
    momentum = resolve_momentum({}, _output(short_return), _output(long_return))

    added = resolve_operator(ADD, {}, left=close, right=volume)
    scaled = resolve_operator(SCALE, {"factor": Decimal("0.5")}, value=_output(added))

    rolling_min = resolve_operator(ROLLING_MIN, {"period": 5}, value=close)
    delayed_min = resolve_operator(DELAY, {"period": 2}, value=_output(rolling_min))

    rolling_max = resolve_operator(ROLLING_MAX, {"period": 5}, value=close)
    max_std = resolve_operator(ROLLING_STD, {"period": 3}, value=_output(rolling_max))

    rolling_var = resolve_operator(ROLLING_VAR, {"period": 5}, value=close)
    variance_sign = resolve_operator(SIGN, {}, value=_output(rolling_var))

    return {
        "temporal_over_rolling": _graph(mean, delta_mean),
        "arithmetic_normalization": _graph(mean20, std20, spread, normalized),
        "covariance_then_abs": _graph(covariance, absolute_covariance),
        "correlation_then_rank": _graph(correlation, ranked),
        "temporal_then_decay": _graph(source_delta, decayed_delta),
        "l2_return_then_cross_percentile": _graph(rolling_return, percentile),
        "l2_volatility_then_cross_rank": _graph(rolling_volatility, cross_rank),
        "l2_wma_then_cross_zscore": _graph(wma, zscore),
        "l2_roc_then_cross_demean": _graph(roc, demeaned),
        "l2_wma_then_delta": _graph(wma_short, wma_delta),
        "l2_roc_then_abs": _graph(roc, absolute_roc),
        "l2_vwap_then_delta": _graph(vwap, vwap_delta),
        "l2_stochastic_k_then_rank": _graph(stochastic, stochastic_rank),
        "l3_momentum_consumes_l2_returns": _graph(short_return, long_return, momentum),
        "binary_arithmetic_then_scale": _graph(added, scaled),
        "rolling_min_then_delay": _graph(rolling_min, delayed_min),
        "rolling_max_then_std": _graph(rolling_max, max_std),
        "rolling_variance_then_sign": _graph(rolling_var, variance_sign),
    }


def test_eighteen_representative_compositions_close_b1_expression_classes() -> None:
    graphs = _representative_compositions()
    assert len(graphs) == 18
    assert len({graph.fingerprint for graph in graphs.values()}) == 18

    close = _source("close")
    wma = OnlyFinancialIndicatorDefinitionResolver(WMA).resolve({"period": 20}, {"price": close})
    changed = OnlyFinancialIndicatorDefinitionResolver(WMA).resolve({"period": 21}, {"price": close})
    assert changed.fingerprint != wma.fingerprint
    assert Decimal("0.000000000001") == wma.numeric.output_quantum


def test_representative_time_series_and_cross_section_compositions_execute_in_research(tmp_path) -> None:
    registry = OnlyCalculationRegistry()
    for registration in (*operator_registrations(), *indicator_registrations()):
        registry.register(registration)
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    store.commit(candidate, partitions)
    executor = OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(registry))
    graphs = _representative_compositions()

    time_series = executor.execute(candidate.snapshot_fingerprint, graphs["temporal_over_rolling"])
    cross_section = executor.execute(candidate.snapshot_fingerprint, graphs["l2_return_then_cross_percentile"])

    assert len(time_series.outputs) == 4
    assert len(cross_section.outputs) == 4
    assert any("percentile" in output.table.column_names for output in cross_section.outputs)
