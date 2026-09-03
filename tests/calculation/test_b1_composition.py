from decimal import Decimal

from onlyalpha_plugin_indicators.registration import (
    ROC,
    VWAP,
    WMA,
    OnlyFinancialIndicatorDefinitionResolver,
)
from onlyalpha_plugin_operators.registration import (
    CROSS_SECTION_PERCENTILE,
    CROSS_SECTION_ZSCORE,
    DECAY_LINEAR,
    DELTA,
    DIVIDE,
    ROLLING_CORRELATION,
    ROLLING_MEAN,
    ROLLING_STD,
    SUBTRACT,
    TS_RANK,
    resolve_operator,
)

from onlyalpha.calculation import (
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationReference,
)


def _source(name: str) -> OnlyCalculationReference:
    return OnlyCalculationReference(None, name, f"bar.{name}")


def _output(definition, name: str = "value") -> OnlyCalculationReference:
    return OnlyCalculationReference(definition.fingerprint, name)


def _graph(*definitions) -> OnlyCalculationGraphDefinition:
    nodes = tuple(OnlyCalculationNodeDefinition(definition) for definition in definitions)
    graph = OnlyCalculationGraphDefinition(nodes)
    assert graph.fingerprint == OnlyCalculationGraphDefinition(tuple(reversed(nodes))).fingerprint
    return graph


def test_six_cross_layer_compositions_close_b1_expression_classes() -> None:
    close, volume = _source("close"), _source("volume")
    mean = resolve_operator(ROLLING_MEAN, {"period": 5}, value=close)
    delta_mean = resolve_operator(DELTA, {"period": 2}, value=_output(mean))

    mean20 = resolve_operator(ROLLING_MEAN, {"period": 20}, value=close)
    std20 = resolve_operator(ROLLING_STD, {"period": 20}, value=close)
    spread = resolve_operator(SUBTRACT, {}, left=close, right=_output(mean20))
    normalized = resolve_operator(DIVIDE, {}, left=_output(spread), right=_output(std20))

    roc = OnlyFinancialIndicatorDefinitionResolver(ROC).resolve({"period": 5}, {"price": close})
    correlation = resolve_operator(ROLLING_CORRELATION, {"period": 10}, left=_output(roc, "roc"), right=volume)
    ranked = resolve_operator(TS_RANK, {"period": 20}, value=_output(correlation))

    percentile = resolve_operator(CROSS_SECTION_PERCENTILE, {}, value=_output(roc, "roc"))

    vwap = OnlyFinancialIndicatorDefinitionResolver(VWAP).resolve({"period": 5}, {"price": close, "volume": volume})
    vwap_delta = resolve_operator(DELTA, {"period": 5}, value=_output(vwap, "vwap"))
    decayed = resolve_operator(DECAY_LINEAR, {"period": 10}, value=_output(vwap_delta))

    wma = OnlyFinancialIndicatorDefinitionResolver(WMA).resolve({"period": 20}, {"price": close})
    zscore = resolve_operator(CROSS_SECTION_ZSCORE, {}, value=_output(wma))

    graphs = (
        _graph(mean, delta_mean),
        _graph(mean20, std20, spread, normalized),
        _graph(roc, correlation, ranked),
        _graph(roc, percentile),
        _graph(vwap, vwap_delta, decayed),
        _graph(wma, zscore),
    )
    assert len({graph.fingerprint for graph in graphs}) == 6
    changed = OnlyFinancialIndicatorDefinitionResolver(WMA).resolve({"period": 21}, {"price": close})
    assert changed.fingerprint != wma.fingerprint
    assert Decimal("0.000000000001") == wma.numeric.output_quantum
