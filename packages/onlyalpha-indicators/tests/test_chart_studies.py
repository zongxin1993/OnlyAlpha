from decimal import Decimal

import pyarrow as pa
from onlyalpha_plugin_indicators.registration import registrations

from onlyalpha.calculation import OnlyCalculationBackendKind


def test_chart_support_exposes_fourteen_default_definitions_with_backend_readiness():
    supported = []
    variants = 0
    for registration in registrations():
        if registration.backend is not OnlyCalculationBackendKind.RESEARCH:
            continue
        backend = registration.provider
        assert callable(getattr(backend, "chart_study_support", None))
        support = backend.chart_study_support(registration.type_definition)
        if support is None:
            continue
        variants += 1
        if support.default_variant:
            supported.append(registration.type_definition.type_id)
        definition = registration.definition_resolver.resolve(support.default_parameters, {})
        inputs = {
            item.name: pa.array([index * 60_000_000_000 for index in range(40)], type=pa.int64())
            if item.name == "start_ns"
            else pa.array([Decimal(10)] * 40, type=pa.decimal128(38, 12))
            for item in definition.inputs
        }
        result = backend.execute_chart_study(definition, inputs)
        from onlyalpha.research.calculation import only_validate_research_output_readiness

        only_validate_research_output_readiness(definition, result.outputs, result.readiness, row_count=40)
        assert set(result.outputs) == set(result.readiness)
        assert {series.output_name for series in support.series} <= set(result.outputs)
    assert len(supported) == len(set(supported)) == 14
    assert variants == 19


def _registered(name: str, version: str):
    return next(
        r
        for r in registrations()
        if r.backend is OnlyCalculationBackendKind.RESEARCH
        and r.type_definition.type_id == f"onlyalpha.indicator.{name}"
        and r.type_definition.semantic_version == version
    )


def _evaluate(name, version, parameters, columns):
    registration = _registered(name, version)
    definition = registration.definition_resolver.resolve(parameters, {})
    arrays = {
        key: pa.array(values, type=pa.int64() if key == "start_ns" else pa.decimal128(38, 12))
        for key, values in columns.items()
    }
    return definition, registration.provider.execute_chart_study(definition, arrays)


def test_wilder_rsi_uses_seed_then_recursive_smoothing_and_flat_is_neutral():
    _, result = _evaluate("rsi", "2", {"period": 3}, {"value": [Decimal(x) for x in (1, 2, 4, 3, 2, 5)]})
    assert result.outputs["value"].to_pylist() == [
        None,
        None,
        None,
        Decimal("75"),
        Decimal("54.545454545455"),
        Decimal("79.591836734694"),
    ]
    assert result.readiness["value"].states.to_pylist() == ["PARTIAL"] * 3 + ["READY"] * 3
    _, flat = _evaluate("rsi", "2", {"period": 2}, {"value": [Decimal(10)] * 4})
    assert flat.outputs["value"].to_pylist() == [None, None, Decimal(50), Decimal(50)]


def test_wilder_atr_uses_previous_close_and_seed_then_recursion():
    _, result = _evaluate(
        "atr",
        "3",
        {"period": 3},
        {
            "high": [Decimal(x) for x in (11, 13, 15, 14)],
            "low": [Decimal(x) for x in (9, 10, 12, 10)],
            "close": [Decimal(x) for x in (10, 12, 14, 11)],
        },
    )
    assert result.outputs["atr"].to_pylist() == [None, None, Decimal("2.666666666667"), Decimal("3.111111111111")]


def test_macd_conventional_histogram_preserves_original_double_variant():
    parameters = {"fast_period": 2, "slow_period": 3, "signal_period": 2}
    columns = {"value": [Decimal(x) for x in (10, 12, 11, 14, 12)]}
    _, old = _evaluate("macd", "1", parameters, columns)
    _, new = _evaluate("macd", "2", parameters, columns)
    assert new.outputs["dif"].equals(old.outputs["dif"])
    assert new.outputs["dea"].equals(old.outputs["dea"])
    for dif, dea, histogram in zip(
        new.outputs["dif"].to_pylist(),
        new.outputs["dea"].to_pylist(),
        new.outputs["histogram"].to_pylist(),
        strict=True,
    ):
        assert histogram == dif - dea
    assert (
        _registered("macd", "1").provider.chart_study_support(_registered("macd", "1").type_definition).default_variant
        is False
    )


def test_slow_stochastic_has_independent_k_d_warmup_and_zero_range_undefined():
    _, result = _evaluate(
        "stochastic",
        "2",
        {"k_period": 2, "smooth_k": 2, "d_period": 2},
        {
            "high": [Decimal(10)] * 5,
            "low": [Decimal(0)] * 5,
            "close": [Decimal(x) for x in (1, 2, 4, 8, 6)],
        },
    )
    assert result.outputs["k"].to_pylist() == [None, None, Decimal(30), Decimal(60), Decimal(70)]
    assert result.outputs["d"].to_pylist() == [None, None, None, Decimal(45), Decimal(65)]
    assert result.readiness["k"].states.to_pylist() == ["PARTIAL", "PARTIAL", "READY", "READY", "READY"]
    _, flat = _evaluate(
        "stochastic",
        "2",
        {"k_period": 1, "smooth_k": 1, "d_period": 1},
        {"high": [Decimal(0)], "low": [Decimal(0)], "close": [Decimal(0)]},
    )
    assert flat.outputs["k"].to_pylist() == [None]
    assert flat.readiness["k"].reasons.to_pylist() == ["VALUE_UNDEFINED"]


def test_utc_day_vwap_resets_from_explicit_bar_start_and_zero_volume_is_undefined():
    day = 86_400_000_000_000
    _, result = _evaluate(
        "vwap",
        "2",
        {},
        {
            "start_ns": [day - 2, day - 1, day, day + 1],
            "high": [Decimal(x) for x in (12, 24, 36, 48)],
            "low": [Decimal(x) for x in (9, 18, 27, 36)],
            "close": [Decimal(x) for x in (9, 18, 27, 36)],
            "volume": [Decimal(x) for x in (1, 3, 0, 2)],
        },
    )
    assert result.outputs["vwap"].to_pylist() == [Decimal(10), Decimal("17.5"), None, Decimal(40)]
    assert result.readiness["vwap"].reasons.to_pylist() == ["NONE", "NONE", "VALUE_UNDEFINED", "NONE"]


def test_new_semantics_incremental_checkpoint_and_hostile_context_match_batch():
    from decimal import ROUND_DOWN, localcontext

    from onlyalpha_plugin_indicators.calibrated import OnlyCalibratedIndicator
    from onlyalpha_plugin_indicators.registration import CALIBRATED_TYPES

    for item in CALIBRATED_TYPES:
        registration = _registered(item.type_id.rsplit(".", 1)[-1], item.semantic_version)
        definition = registration.definition_resolver.resolve({}, {})
        columns = {
            i.name: [index * 60_000_000_000 for index in range(50)]
            if i.name == "start_ns"
            else [Decimal(index % 7 + (12 if i.name == "high" else 1 if i.name == "low" else 4)) for index in range(50)]
            for i in definition.inputs
        }
        arrays = {
            key: pa.array(values, type=pa.int64() if key == "start_ns" else pa.decimal128(38, 12))
            for key, values in columns.items()
        }
        reference = registration.provider.execute_chart_study(definition, arrays)
        kernel = OnlyCalibratedIndicator(definition)
        with localcontext() as hostile:
            hostile.prec = 3
            hostile.rounding = ROUND_DOWN
            hostile.Emax = 3
            hostile.Emin = -3
            hostile.traps[__import__("decimal").Inexact] = True
            for index in range(50):
                if index == 25:
                    restored = OnlyCalibratedIndicator(definition)
                    restored.restore_checkpoint(kernel.capture_checkpoint())
                    kernel = restored
                row = kernel.update({key: values[index] for key, values in columns.items()})
                for key, value in row.items():
                    assert value == reference.outputs[key][index].as_py()


def test_checkpoint_rejects_wrong_definition_or_missing_state_without_mutating_kernel():
    import copy

    import pytest
    from onlyalpha_plugin_indicators.calibrated import OnlyCalibratedIndicator

    registration = _registered("rsi", "2")
    definition = registration.definition_resolver.resolve({"period": 3}, {})
    kernel = OnlyCalibratedIndicator(definition)
    kernel.update({"value": Decimal(10)})
    original = kernel.capture_checkpoint()
    for mutation in ("definition", "state", "row", "count"):
        payload = copy.deepcopy(original)
        if mutation == "definition":
            payload["definition"] = "0" * 64
        elif mutation == "state":
            payload["state"] = {}
        elif mutation == "row":
            payload["rows"][0]["value"] = "NaN"
        else:
            payload["state"]["count"] = True
        with pytest.raises(ValueError):
            kernel.restore_checkpoint(payload)
        assert kernel.capture_checkpoint() == original


def test_propagated_missing_window_recovers_without_false_unavailable():
    from onlyalpha.research.calculation import only_validate_research_output_readiness

    definition, result = _evaluate("wma", "1", {"period": 2}, {"price": [None, Decimal(2), Decimal(4), Decimal(6)]})
    assert result.outputs["value"].to_pylist() == [None, None, Decimal("3.333333333333"), Decimal("5.333333333333")]
    assert result.readiness["value"].states.to_pylist() == ["UNAVAILABLE", "UNAVAILABLE", "READY", "READY"]
    only_validate_research_output_readiness(definition, result.outputs, result.readiness, row_count=4)


def test_incremental_numeric_failure_keeps_prior_checkpoint():
    from decimal import DecimalException

    import pytest
    from onlyalpha_plugin_indicators.calibrated import OnlyCalibratedIndicator

    registration = _registered("macd", "2")
    definition = registration.definition_resolver.resolve({}, {})
    kernel = OnlyCalibratedIndicator(definition)
    kernel.update({"value": Decimal(10)})
    before = kernel.capture_checkpoint()
    with pytest.raises(DecimalException):
        kernel.update({"value": Decimal("1e1000000")})
    assert kernel.capture_checkpoint() == before


def test_chart_capacity_exhaustion_rejects_before_any_kernel_call(monkeypatch):
    import pytest
    from onlyalpha_plugin_indicators.research import OnlyOfficialResearchIndicatorBackend

    calls = []

    def forbidden_execute(*args):
        calls.append(args)
        raise AssertionError("capacity rejection must precede execution")

    monkeypatch.setattr(OnlyOfficialResearchIndicatorBackend, "execute", forbidden_execute)
    for name, version, parameters, count in (
        ("wma", "1", {"period": 10000}, 501),
        ("rolling_volatility", "1", {"period": 10000}, 501),
        ("stochastic", "2", {"k_period": 10000, "smooth_k": 10000, "d_period": 10000}, 1),
    ):
        registration = _registered(name, version)
        definition = registration.definition_resolver.resolve(parameters, {})
        inputs = {item.name: pa.array([Decimal(10)] * count, type=pa.decimal128(38, 12)) for item in definition.inputs}
        with pytest.raises(ValueError, match="CHART_STUDY_CAPACITY_EXCEEDED"):
            registration.provider.execute_chart_study(definition, inputs)
    assert calls == []


def test_chart_work_budget_accepts_exact_boundary_and_rejects_next_unit():
    import pytest
    from onlyalpha_plugin_indicators.chart import require_chart_capacity

    definition = _registered("wma", "1").definition_resolver.resolve({"period": 10000}, {})
    require_chart_capacity(definition, 500)
    with pytest.raises(ValueError, match="CHART_STUDY_CAPACITY_EXCEEDED"):
        require_chart_capacity(definition, 501)


def test_financial_numeric_context_is_directly_provable_without_decorator_wrapper():
    from decimal import getcontext, localcontext

    from onlyalpha_plugin_indicators.financial_semantics import financial_numeric_context

    definition = _registered("rsi", "2").definition_resolver.resolve({}, {})
    assert not hasattr(financial_numeric_context, "__wrapped__")
    with localcontext() as caller:
        caller.prec = 3
        with financial_numeric_context(definition):
            assert getcontext().prec == definition.numeric.precision
        assert getcontext().prec == 3
