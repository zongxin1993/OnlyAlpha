"""Installed transient invocation proof, not Market Data or scientific certification."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import (
    ROUND_05UP,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    DefaultContext,
    InvalidOperation,
    getcontext,
    localcontext,
)
from pathlib import Path
from threading import Barrier

import pyarrow as pa
import pytest
from onlyalpha_plugin_indicators import research
from onlyalpha_plugin_indicators.provider import quant_asset_provider

from onlyalpha.application.chart_study_input import OnlyChartStudyClosedHistoryInput
from onlyalpha.application.chart_study_numeric import (
    OnlyChartStudySmaInvocation,
    _require_sma_definition,
    _require_sma_registration,
)
from onlyalpha.calculation.chart_decimal import only_chart_sma_effective_numeric, only_chart_sma_numeric_binding
from onlyalpha.calculation.decimal_execution import only_decimal_context
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationReference,
    OnlyNumericDefinition,
)
from onlyalpha.calculation.implementation import OnlyCalculationImplementationResource
from onlyalpha.quant_assets.catalog import (
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetCatalogManager,
    only_discover_quant_asset_providers,
)

pytestmark = pytest.mark.contract
DECIMAL = pa.decimal128(38, 12)


def composition(provider=None):
    catalog = (
        OnlyQuantAssetCatalogGeneration((provider,)) if provider is not None else only_discover_quant_asset_providers()
    )
    registry = catalog.calculation_registry()
    return OnlyChartStudySmaInvocation(registry, catalog), registry, catalog


def values(*items):
    return {"value": pa.array([Decimal(item) for item in items], type=DECIMAL)}


def observe(result):
    return (
        tuple(format(value, "f") for value in result.outputs["value"].to_pylist()),
        tuple(result.readiness["value"].states.to_pylist()),
        tuple(result.readiness["value"].reasons.to_pylist()),
    )


def invoke(invocation, inputs, period=20):
    return invocation._invoke_numeric(
        {"period": period, "price_field": "CLOSE"}, inputs, capability_fingerprint=invocation.admission.fingerprint
    )


@pytest.mark.parametrize("period", (1, 20, 10000))
def test_same_explicit_context_preserves_definition_and_backend_atomic_values(period):
    invocation, registry, _ = composition()
    registration = invocation.admission.registration
    definition = registry.rematerialize_definition(
        registration.implementation_manifest.calculation_type_reference, {"period": period}, {}
    )
    before = definition.fingerprint, definition.to_dict(), registration.type_definition.descriptor()
    inputs = values(*(str(index) for index in range(25)))
    with localcontext(only_decimal_context(only_chart_sma_effective_numeric(definition.numeric))):
        legacy = registration.provider.execute_with_readiness(definition, inputs)
        oracle = [
            (
                sum((Decimal(value) for value in range(max(0, index + 1 - period), index + 1)), Decimal(0))
                / Decimal(min(period, index + 1))
            ).quantize(Decimal("0.000000000001"))
            for index in range(25)
        ]
    result = invoke(invocation, inputs, period)
    assert observe(result) == observe(legacy)
    assert result.outputs["value"].to_pylist() == oracle
    assert result.outputs["value"][0].as_py() == Decimal("0.000000000000")
    assert result.readiness["value"].states.to_pylist() == [
        "PARTIAL" if index + 1 < period else "READY" for index in range(25)
    ]
    assert result.readiness["value"].reasons.to_pylist() == [
        "WARMUP_INCOMPLETE" if index + 1 < period else "NONE" for index in range(25)
    ]
    assert before == (definition.fingerprint, definition.to_dict(), registration.type_definition.descriptor())
    assert definition.numeric.rounding == "CONTEXT"
    assert definition.semantic_version == "1"


def context_state(context):
    return (
        context.prec,
        context.rounding,
        context.Emin,
        context.Emax,
        context.capitals,
        context.clamp,
        dict(context.traps),
        dict(context.flags),
    )


ROUNDINGS = (
    ROUND_05UP,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
)


@pytest.mark.parametrize("rounding", ROUNDINGS)
@pytest.mark.parametrize("trapped", (False, True))
@pytest.mark.parametrize("preset_flags", (False, True))
def test_hostile_ambient_context_has_no_influence_and_is_preserved_on_success_and_error(
    rounding, trapped, preset_flags
):
    invocation, _, _ = composition()
    expected = observe(invoke(invocation, values("0", "1", "0", "0.000000000001"), 3))
    with localcontext() as context:
        context.prec, context.rounding = 2, rounding
        context.Emin, context.Emax, context.capitals, context.clamp = -2, 2, 0, 1
        for signal in context.traps:
            context.traps[signal] = trapped
            context.flags[signal] = preset_flags
        original = context_state(context)
        assert observe(invoke(invocation, values("0", "1", "0", "0.000000000001"), 3)) == expected
        assert context_state(context) == original
        with pytest.raises(InvalidOperation):
            invoke(invocation, values("10000000000000000"), 1)
        assert context_state(context) == original


def test_default_context_is_not_numeric_authority():
    invocation, _, _ = composition()
    expected = observe(invoke(invocation, values("1", "0", "0"), 3))
    saved = DefaultContext.copy()
    try:
        DefaultContext.prec, DefaultContext.rounding = 1, ROUND_UP
        DefaultContext.Emin, DefaultContext.Emax, DefaultContext.clamp = -1, 1, 1
        for signal in DefaultContext.traps:
            DefaultContext.traps[signal] = True
            DefaultContext.flags[signal] = True
        assert observe(invoke(invocation, values("1", "0", "0"), 3)) == expected
    finally:
        for field in ("prec", "rounding", "Emin", "Emax", "capitals", "clamp"):
            setattr(DefaultContext, field, getattr(saved, field))
        DefaultContext.traps = dict(saved.traps)
        DefaultContext.flags = dict(saved.flags)


def test_halfway_rounding_is_explicit_even_not_an_ambient_default():
    invocation, _, _ = composition()
    with localcontext() as context:
        context.rounding = ROUND_UP
        result = invoke(invocation, values("0", "0.000000000001"), 2)
    assert observe(result) == (
        ("0.000000000000", "0.000000000000"),
        ("PARTIAL", "READY"),
        ("WARMUP_INCOMPLETE", "NONE"),
    )


def test_barrier_concurrent_isolated_invocations_preserve_each_thread_context():
    invocations = [composition()[0] for _ in ROUNDINGS]
    barrier = Barrier(len(ROUNDINGS))

    def execute(pair):
        index, invocation = pair
        context = getcontext()
        context.prec, context.rounding, context.Emin, context.Emax, context.clamp = 2, ROUNDINGS[index], -2, 2, 1
        for signal in context.flags:
            context.flags[signal] = True
            context.traps[signal] = index % 2 == 0
        before = context_state(context)
        barrier.wait()
        result = observe(invoke(invocation, values("0", "2", "4", "8"), 3))
        assert context_state(context) == before
        return result

    with ThreadPoolExecutor(max_workers=len(ROUNDINGS)) as pool:
        observations = list(pool.map(execute, enumerate(invocations)))
    assert all(item == observations[0] for item in observations)
    assert observations[0][0] == ("0.000000000000", "1.000000000000", "2.000000000000", "4.666666666667")


@pytest.mark.parametrize(
    "parameters",
    (
        {"period": True},
        {"period": "20"},
        {"period": 0},
        {"period": -1},
        {"period": 10001},
        {"period": 1.0},
        {"price_field": "VOLUME"},
        {"price_field": "close"},
        {"output": "zone"},
        {"type_id": "onlyalpha.indicator.ema"},
        {"semantic_version": "2"},
        {"backend": "TRADING"},
        {"source": "browser"},
        {"include_unclosed_preview": True},
        {"script": "1+1"},
    ),
)
def test_unadmitted_parameters_and_families_are_rejected(parameters):
    invocation, _, _ = composition()
    with pytest.raises(ValueError, match="CHART_STUDY_INPUT_INVALID"):
        invocation._invoke_numeric(parameters, values("1"), capability_fingerprint=invocation.admission.fingerprint)


@pytest.mark.parametrize(
    "inputs",
    (
        {},
        {"other": pa.array([Decimal(1)], type=DECIMAL)},
        {"value": ["1"]},
        {"value": pa.array([1])},
        {"value": pa.array([1.0])},
        {"value": pa.array([None], type=DECIMAL)},
        {"value": pa.array([], type=DECIMAL)},
        {"value": pa.array([Decimal(1)] * 2001, type=DECIMAL)},
        {"value": pa.array([Decimal(1)], type=pa.decimal256(76, 12))},
        {"value": pa.array([Decimal(1)], type=DECIMAL), "close": pa.array([Decimal(1), Decimal(2)], type=DECIMAL)},
    ),
)
def test_invalid_input_members_types_nulls_lengths_and_bounds_fail_closed(inputs):
    invocation, _, _ = composition()
    with pytest.raises(ValueError, match="CHART_STUDY_INPUT_INVALID"):
        invoke(invocation, inputs)


def test_input_bound_and_chunked_decimal_are_valid_without_scientific_dependency():
    invocation, _, _ = composition()
    inputs = {"value": pa.chunked_array([[Decimal(0)] * 1000, [Decimal(0)] * 1000], type=DECIMAL)}
    for _ in range(2):
        result = invoke(invocation, inputs, 1)
        assert len(result.outputs["value"]) == 2000
        assert set(result.readiness["value"].states.to_pylist()) == {"READY"}
    assert inputs["value"].num_chunks == 2
    assert set(vars(invocation)) == {"_registry", "_catalog", "_slot", "_admission", "_fingerprint"}


@pytest.mark.parametrize("mutation", ("dependency", "old_manifest", "resource_hash", "missing_resource", "readiness"))
def test_manifest_or_readiness_proof_mutation_is_unavailable(mutation):
    provider = quant_asset_provider()
    registration = next(item for item in provider.calculation_registrations if item.readiness_contract_versions)
    manifest = registration.implementation_manifest
    if mutation == "dependency":
        manifest = replace(
            manifest,
            semantic_dependencies=tuple(
                replace(item, artifact_fingerprint="a" * 64)
                if item.dependency_id == "onlyalpha.decimal.execution"
                else item
                for item in manifest.semantic_dependencies
            ),
        )
    elif mutation == "old_manifest":
        manifest = replace(
            manifest,
            semantic_dependencies=tuple(
                item for item in manifest.semantic_dependencies if not item.dependency_id.startswith("onlyalpha.")
            ),
        )
    elif mutation == "resource_hash":
        manifest = replace(
            manifest, resources=tuple(replace(item, byte_sha256="a" * 64) for item in manifest.resources)
        )
    elif mutation == "missing_resource":
        manifest = replace(
            manifest, resources=(*manifest.resources, OnlyCalculationImplementationResource("absent.py", "a" * 64))
        )
    changed = replace(
        registration,
        implementation_manifest=manifest,
        readiness_contract_versions=() if mutation == "readiness" else (1,),
    )
    expected = (
        "CHART_STUDY_DEPENDENCY_UNAVAILABLE"
        if mutation in {"dependency", "old_manifest"}
        else "CHART_STUDY_.*UNAVAILABLE"
    )
    with pytest.raises(ValueError, match=expected):
        _require_sma_registration(changed)


def test_equal_copied_registration_is_not_same_process_ownership():
    invocation, registry, catalog = composition()
    registration = invocation.admission.registration
    key = next(key for key, item in registry._registrations.items() if item is registration)
    registry._registrations[key] = replace(registration)
    with pytest.raises(ValueError, match="CHART_STUDY_UNAVAILABLE"):
        OnlyChartStudySmaInvocation(registry, catalog)
    with pytest.raises(ValueError, match="CHART_STUDY_UNAVAILABLE"):
        invoke(invocation, values("1"))


def test_second_discovery_cannot_supply_catalog_for_an_earlier_registry():
    invocation, registry, catalog = composition()
    second = only_discover_quant_asset_providers()
    assert second.generation_fingerprint == catalog.generation_fingerprint
    with pytest.raises(ValueError, match="CHART_STUDY_UNAVAILABLE"):
        OnlyChartStudySmaInvocation(registry, second)
    assert invoke(invocation, values("0"), 1).outputs["value"][0].as_py() == Decimal("0")


def test_helper_replacement_cannot_execute_under_authentic_resource_hash(monkeypatch):
    invocation, _, _ = composition()
    calls = []

    def counterfeit(*args):
        calls.append(args)
        return Decimal(99)

    monkeypatch.setattr(research, "_mean", counterfeit)
    with pytest.raises(ValueError, match="CHART_STUDY_IMPLEMENTATION_UNAVAILABLE"):
        invoke(invocation, values("1"))
    assert calls == []


def test_provider_version_content_drift_is_rejected_and_new_version_changes_projection():
    invocation, _, catalog = composition()
    provider = invocation.admission.provider
    manager = OnlyQuantAssetCatalogManager(catalog)
    registrations = tuple(
        item for item in provider.calculation_registrations if item.backend is OnlyCalculationBackendKind.RESEARCH
    )
    changed = replace(provider, calculation_registrations=registrations)
    with pytest.raises(ValueError, match="QUANT_ASSET_PROVIDER_VERSION_CONTENT_DRIFT"):
        manager.refresh(lambda: OnlyQuantAssetCatalogGeneration((changed,)))
    candidate = replace(changed, manifest=replace(changed.manifest, provider_version="8"))
    newer = replace(invocation.admission, provider=candidate, catalog=OnlyQuantAssetCatalogGeneration((candidate,)))
    assert newer.registration.implementation_manifest == invocation.admission.registration.implementation_manifest
    assert newer.fingerprint != invocation.admission.fingerprint
    with pytest.raises(ValueError, match="CHART_STUDY_REGISTRATION_CHANGED"):
        invocation._invoke_numeric({}, values("1"), capability_fingerprint=newer.fingerprint)
    with pytest.raises(ValueError, match="CHART_STUDY_UNAVAILABLE"):
        composition(candidate)


def test_complete_different_catalog_uses_retained_actual_install_objects_not_descriptions():
    invocation, _, catalog = composition()
    owner = invocation.admission.provider
    # A bounded alternative composition of actual discovered objects, no rediscovery or copied owners.
    subset = OnlyQuantAssetCatalogGeneration((owner,))
    object.__setattr__(
        subset, "_installed_origins", tuple(origin for origin in catalog._installed_origins if origin.provider is owner)
    )
    newer = OnlyChartStudySmaInvocation(subset.calculation_registry(), subset)
    assert newer.admission.registration is invocation.admission.registration
    assert newer.admission.provider is owner
    assert newer.admission.fingerprint != invocation.admission.fingerprint
    assert invoke(newer, values("1"), 1).outputs["value"][0].as_py() == Decimal("1")
    with pytest.raises(ValueError, match="CHART_STUDY_REGISTRATION_CHANGED"):
        newer._invoke_numeric({}, values("1"), capability_fingerprint=invocation.admission.fingerprint)


def test_missing_owner_does_not_become_catalog_absence():
    invocation, registry, _ = composition()
    with pytest.raises(ValueError, match="CHART_STUDY_UNAVAILABLE"):
        OnlyChartStudySmaInvocation(registry, OnlyQuantAssetCatalogGeneration(()))
    binding = only_chart_sma_numeric_binding(invocation.admission.registration.type_definition.numeric)
    assert binding["resolution_policy"] == "CONTEXT_HALF_EVEN_V1"
    assert binding["core_policy"]["entry_flags"] == "CLEAR"
    with pytest.raises(ValueError, match="CHART_STUDY_NUMERIC_UNAVAILABLE"):
        only_chart_sma_effective_numeric(OnlyNumericDefinition(rounding="ROUND_HALF_EVEN"))
    with pytest.raises(ValueError, match="CHART_STUDY_NUMERIC_UNAVAILABLE"):
        only_chart_sma_effective_numeric(OnlyNumericDefinition(output_quantum=Decimal("0.0000000000010")))


def test_slot_rejects_reentry_without_queue_and_is_released_after_decimal_failure():
    invocation, _, _ = composition()
    fingerprint = invocation.admission.fingerprint
    assert invocation._slot.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match="CHART_STUDY_CAPACITY_EXCEEDED"):
            invocation._invoke_numeric({}, values("1"), capability_fingerprint=fingerprint)
    finally:
        invocation._slot.release()
    with pytest.raises(InvalidOperation):
        invocation._invoke_numeric({"period": 1}, values("10000000000000000"), capability_fingerprint=fingerprint)
    assert observe(invocation._invoke_numeric({"period": 1}, values("0"), capability_fingerprint=fingerprint)) == (
        ("0.000000000000",),
        ("READY",),
        ("NONE",),
    )


@pytest.mark.parametrize(
    "raw",
    (values("1"), {"bars": [{"close": "1", "closed": True}]}, None, object.__new__(OnlyChartStudyClosedHistoryInput)),
)
def test_admitted_closed_history_entry_rejects_arrays_browser_bars_and_forged_handoff(raw):
    invocation, _, _ = composition()
    with pytest.raises(ValueError, match="CHART_STUDY_INPUT_UNAVAILABLE"):
        invocation.invoke_closed_history({}, raw, capability_fingerprint=invocation.admission.fingerprint)


def test_admitted_input_comes_from_owning_authorized_complete_read_and_withdrawal_is_rechecked(tmp_path: Path):
    from onlyalpha.application.source_read_access import OnlySourceReadAccessError
    from onlyalpha.market_data.durable.range_query import OnlyBarWindowAnchorKind
    from tests.application.test_market_data_product import INSTRUMENT, _range, _reference, _service
    from tests.application.test_source_read_access import TOKEN, _authority

    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    authority = _authority(reference)
    session = authority.authenticate("Bearer " + TOKEN)
    start, end = _range()
    # Isolated deterministic owning fixture preparation precedes the zero-write baseline.
    harness.service.acquire_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start, end_ns=end)
    before = harness.catalog.mutations, harness.service._facts.writes
    handoff = harness.service.read_chart_study_input(
        reference,
        instrument_id=str(INSTRUMENT),
        anchor_kind=OnlyBarWindowAnchorKind.BEFORE_TIME,
        target_bar_count=2,
        before_ns=end,
        read_session=session,
    )
    invocation, _, _ = composition()
    result = invocation.invoke_closed_history(
        {"period": 1}, handoff, capability_fingerprint=invocation.admission.fingerprint
    )
    assert observe(result)[0] == ("101.000000000000", "101.000000000000")
    from onlyalpha.application.chart_study_input import _only_issue_chart_study_closed_history_input

    window = handoff.require_window()
    for changed in (
        replace(window, closed_only=False),
        replace(window, coverage=replace(window.coverage, status="INCOMPLETE")),
        replace(window, revision_evidence=()),
        replace(window, history_projection_fingerprint=None),
        replace(window, bars=tuple(reversed(window.bars))),
        replace(window, bars=(replace(window.bars[0], closed=False), *window.bars[1:])),
        replace(window, resolved_end_ns=window.resolved_end_ns + 1),
    ):
        with pytest.raises(ValueError, match="CHART_STUDY_INPUT_UNAVAILABLE"):
            _only_issue_chart_study_closed_history_input(changed, session)
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_FORBIDDEN"):
        _only_issue_chart_study_closed_history_input(
            replace(window, source_selection=replace(window.source_selection, environment="SIM")), session
        )
    assert before == (harness.catalog.mutations, harness.service._facts.writes)
    authority.withdraw()
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_UNAUTHORIZED"):
        invocation.invoke_closed_history({}, handoff, capability_fingerprint=invocation.admission.fingerprint)


@pytest.mark.parametrize("constant", ("_Q", "_DECIMAL", "equal_quantum_different_exponent"))
def test_loaded_numeric_constant_mutation_cannot_execute_under_authentic_code(monkeypatch, constant):
    invocation, _, _ = composition()
    if constant == "equal_quantum_different_exponent":
        quantum = Decimal("0.0000000000010")
        assert quantum == research._Q and quantum.as_tuple() != research._Q.as_tuple()
        monkeypatch.setattr(research, "_Q", quantum)
    else:
        monkeypatch.setattr(research, constant, Decimal("0.01") if constant == "_Q" else pa.decimal128(38, 2))
    with pytest.raises(ValueError, match="CHART_STUDY_IMPLEMENTATION_UNAVAILABLE"):
        invoke(invocation, values("1"))


@pytest.mark.parametrize("mutation", ("input_type", "output_unit", "source_member", "parameters"))
def test_exact_definition_requires_complete_ports_source_reference_and_requested_parameters(mutation):
    invocation, _, _ = composition()
    registration = invocation.admission.registration
    definition = registration.definition_resolver.resolve({"period": 20}, {})
    if mutation == "input_type":
        changed = replace(
            definition, inputs=(replace(definition.inputs[0], data_type=OnlyCalculationDataType.INTEGER),)
        )
    elif mutation == "output_unit":
        changed = replace(definition, outputs=(replace(definition.outputs[0], unit="COUNTERFEIT"),))
    elif mutation == "source_member":
        changed = replace(
            definition, input_bindings={"value": OnlyCalculationReference(None, "counterfeit", "bar.close")}
        )
    else:
        changed = replace(
            definition,
            parameters={"period": 21, "price_field": "CLOSE"},
            warmup=replace(definition.warmup, minimum_observations=21),
        )
    assert changed.fingerprint != definition.fingerprint
    with pytest.raises(ValueError, match="CHART_STUDY_UNAVAILABLE"):
        _require_sma_definition(changed, registration.type_definition, {"period": 20})
