"""Owning single-read Chart Query and installed numeric SPI, never scientific issuance."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from threading import Event

import pytest

from onlyalpha.application.chart_study_product_query import (
    OnlyChartStudyProductQueryService,
    OnlyChartStudyQueryError,
    OnlyChartStudyRequestV1,
)
from onlyalpha.application.source_read_access import OnlySourceReadAccessError
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market_data.durable.range_query import OnlyBarWindowAnchorKind
from tests.application.test_chart_study_numeric import composition
from tests.application.test_market_data_product import BASE, INSTRUMENT, MINUTE_NS, _reference, _service
from tests.application.test_source_read_access import TOKEN, _authority

pytestmark = pytest.mark.contract
SEMANTIC = OnlyBarSemantic.fixed_duration(15)


def arrange(tmp_path, *, period=20, seed=True, minutes=15, instrument=INSTRUMENT):
    semantic = OnlyBarSemantic.fixed_duration(minutes)
    harness = _service(tmp_path, native_minutes=tuple(sorted({1, minutes})))
    reference = _reference(harness.revision_fingerprint)
    authority = _authority(reference)
    session = authority.authenticate("Bearer " + TOKEN)
    end = OnlyTimestamp.from_datetime(BASE).unix_nanos
    count = 25
    if seed:
        harness.service.acquire_bars(
            reference,
            instrument_id=str(instrument),
            start_ns=end - count * minutes * MINUTE_NS,
            end_ns=end,
            bar_semantic=semantic,
        )
    invocation, _, _ = composition()
    query = OnlyChartStudyProductQueryService(harness.service, invocation)
    admission = query.capabilities(session)
    window = harness.service.query_bars(
        reference,
        instrument_id=str(instrument),
        anchor_kind=OnlyBarWindowAnchorKind.BEFORE_TIME,
        before_ns=end,
        target_bar_count=count,
        bar_semantic=semantic,
        read_session=session,
    )
    request = OnlyChartStudyRequestV1(
        reference,
        str(instrument),
        semantic,
        end,
        count,
        period,
        window.history_projection_fingerprint or "a" * 64,
        only_canonical_fingerprint(admission.registration.type_definition.descriptor()),
        admission.registration.implementation_manifest.implementation_fingerprint,
        admission.fingerprint,
    )
    return harness, query, request, session, authority


@pytest.mark.parametrize("period", (1, 20, 30, 10000))
def test_exact_query_projects_backend_readiness_and_never_writes(tmp_path, period, monkeypatch):
    h, q, request, session, _ = arrange(tmp_path, period=period)
    before = h.catalog.mutations, h.service._facts.writes, h.provider.sessions
    reads = []
    original = h.service._ranges.read

    def observe(*args):
        reads.append(args)
        return original(*args)

    monkeypatch.setattr(h.service._ranges, "read", observe)
    first = q.evaluate(request, session)
    second = q.evaluate(request, session)
    assert len(reads) == 2  # Exactly one owning range observation per evaluation.
    assert before == (h.catalog.mutations, h.service._facts.writes, h.provider.sessions)
    assert first.window == second.window
    assert first.definition.fingerprint == second.definition.fingerprint
    assert first.execution.outputs["value"].to_pylist() == [Decimal("101.000000000000")] * 25
    assert first.execution.readiness["value"].states.to_pylist() == [
        "PARTIAL" if n < period else "READY" for n in range(1, 26)
    ]
    assert first.execution.readiness == second.execution.readiness
    assert first.window.bars[0].bar_start_ns == request.before_ns - 25 * 15 * MINUTE_NS


def test_incomplete_coverage_is_original_single_observation_without_numeric_execution(tmp_path):
    h, q, request, session, _ = arrange(tmp_path, seed=False)
    assert q._invocation._slot.acquire(blocking=False)
    try:
        result = q.evaluate(request, session)
    finally:
        q._invocation._slot.release()
    assert result.execution is None and result.window.coverage.status == "INCOMPLETE"
    assert result.window.coverage.gaps and result.window.history_projection_fingerprint is None
    assert h.provider.sessions == 0 and h.service._facts.writes == 0


def test_exact_grant_is_checked_before_registration_source_or_compute(tmp_path, monkeypatch):
    h, q, request, session, authority = arrange(tmp_path)
    calls = []
    monkeypatch.setattr(q, "capabilities", lambda *a: calls.append(a))
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_FORBIDDEN"):
        q.evaluate(
            replace(request, reference=replace(request.reference, integration_revision_fingerprint="b" * 64)), session
        )
    authority.withdraw()
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_UNAUTHORIZED"):
        q.evaluate(request, session)
    assert calls == []


@pytest.mark.parametrize(
    "field",
    (
        "expected_capability_projection_fingerprint",
        "expected_descriptor_fingerprint",
        "expected_implementation_fingerprint",
        "expected_history_projection_fingerprint",
    ),
)
def test_complete_different_identities_are_changed_not_unavailable(tmp_path, field):
    _, q, request, session, _ = arrange(tmp_path)
    with pytest.raises(OnlyChartStudyQueryError) as error:
        q.evaluate(replace(request, **{field: "b" * 64}), session)
    assert error.value.status == 409
    assert error.value.code == (
        "CHART_STUDY_DATA_CHANGED" if field.startswith("expected_history") else "CHART_STUDY_REGISTRATION_CHANGED"
    )


def test_missing_capability_proof_precedes_identity_difference(tmp_path):
    _, q, request, session, _ = arrange(tmp_path)
    q._invocation._registry._registrations.clear()
    with pytest.raises(OnlyChartStudyQueryError) as error:
        q.evaluate(replace(request, expected_capability_projection_fingerprint="b" * 64), session)
    assert error.value.status == 503 and error.value.code == "CHART_STUDY_CAPABILITY_UNAVAILABLE"


@pytest.mark.parametrize("kind", ("unavailable", "corrupt"))
def test_owning_unavailable_and_corrupt_are_not_incomplete_or_changed(tmp_path, kind):
    h, q, request, session, _ = arrange(tmp_path)
    if kind == "unavailable":
        h.faults.fact_read = RuntimeError("secret-bearing provider error")
    else:
        h.faults.corrupt_seal = True
    with pytest.raises(OnlyChartStudyQueryError) as error:
        q.evaluate(replace(request, expected_history_projection_fingerprint="b" * 64), session)
    assert error.value.status == (503 if kind == "unavailable" else 500)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("value", (True, 0, 10001, "20", 20.0))
def test_period_exact_primitive_and_bounds(tmp_path, value):
    _, _, request, _, _ = arrange(tmp_path, seed=False)
    with pytest.raises(OnlyChartStudyQueryError):
        replace(request, period=value)


def test_one_outer_slot_remains_charged_through_owning_read_and_withdrawal(tmp_path, monkeypatch):
    h, q, request, session, authority = arrange(tmp_path)
    entered, release = Event(), Event()
    original = h.service._ranges.read

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(h.service._ranges, "read", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(q.evaluate, request, session)
        assert entered.wait(5)
        with pytest.raises(OnlyChartStudyQueryError, match="CHART_STUDY_CAPACITY_UNAVAILABLE"):
            q.evaluate(request, session)
        authority.withdraw()
        release.set()
        with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_UNAUTHORIZED"):
            pending.result()
    assert q._slot.acquire(blocking=False)
    q._slot.release()


def test_derived_native_mismatch_is_refused_before_range_read(tmp_path, monkeypatch):
    h, q, request, session, _ = arrange(tmp_path, seed=False)
    h.factory.native_minutes = (1,)
    calls = []
    monkeypatch.setattr(h.service._ranges, "read", lambda *a: calls.append(a))
    with pytest.raises(OnlyChartStudyQueryError, match="CHART_STUDY_INPUT_UNSUPPORTED"):
        q.evaluate(request, session)
    assert calls == []


@pytest.mark.parametrize(
    "shape,expected",
    (
        ("empty", 404),
        ("duplicate", 503),
        ("wrong_family", 503),
        ("wrong_owner", 503),
        ("wrong_venue", 503),
        ("wrong_market", 503),
        ("missing_instrument", 503),
        ("wrong_container", 503),
    ),
)
def test_instrument_absence_requires_complete_unique_scoped_proof(tmp_path, monkeypatch, shape, expected):
    h, q, request, session, _ = arrange(tmp_path, seed=False)
    original = h.factory.list_instruments

    def malformed(query):
        values = original(query)
        if shape == "empty":
            return ()
        if shape == "duplicate":
            return values + values
        if shape == "wrong_family":
            return (object(),)
        if shape == "wrong_container":
            return list(values)
        if shape == "missing_instrument":
            return (replace(values[0], instrument=None),)
        if shape == "wrong_venue":
            return (replace(values[0], venue="OTHER"),)
        if shape == "wrong_market":
            return (replace(values[0], market="OTHER"),)
        return (
            replace(
                values[0], instrument=replace(values[0].instrument, instrument_id=type(INSTRUMENT).parse("OTHER.TEST"))
            ),
        )

    monkeypatch.setattr(h.factory, "list_instruments", malformed)
    reads = []
    monkeypatch.setattr(h.service._ranges, "read", lambda *a: reads.append(a))
    with pytest.raises(OnlyChartStudyQueryError) as error:
        q.evaluate(request, session)
    assert error.value.status == expected
    assert reads == []


@pytest.mark.parametrize("seed", (False, True))
def test_off_grid_window_is_invalid_before_history_io(tmp_path, seed):
    _, _, request, _, _ = arrange(tmp_path, seed=seed)
    with pytest.raises(OnlyChartStudyQueryError, match="CHART_STUDY_REQUEST_INVALID"):
        replace(request, before_ns=request.before_ns + 1)


@pytest.mark.parametrize("minutes", (1, 3, 5, 15, 30, 60, 120, 240))
def test_source_catalog_eth_and_native_duration_are_proved_per_request(tmp_path, monkeypatch, minutes):
    from tests.application import test_market_data_product as owner_fixture

    eth = type(INSTRUMENT).parse("ETHUSDT.TEST")
    monkeypatch.setattr(owner_fixture, "INSTRUMENT", eth)
    h, q, request, session, _ = arrange(tmp_path, minutes=minutes, instrument=eth)
    before = h.catalog.mutations, h.service._facts.writes, h.provider.sessions
    first = q.evaluate(request, session)
    second = q.evaluate(request, session)
    assert first.window.instrument_id == str(eth)
    assert first.window.bar_semantic == OnlyBarSemantic.fixed_duration(minutes)
    assert first.window.resolved_start_ns == request.before_ns - 25 * minutes * MINUTE_NS
    assert first.window.resolution_mode == "PROVIDER_NATIVE"
    assert first.window.history_projection_fingerprint == second.window.history_projection_fingerprint
    assert first.window.revision_evidence == second.window.revision_evidence
    assert first.execution.outputs["value"].to_pylist() == [Decimal("101.000000000000")] * 25
    assert before == (h.catalog.mutations, h.service._facts.writes, h.provider.sessions)


def test_capability_binds_owning_input_support_policy(tmp_path):
    _, q, _, session, _ = arrange(tmp_path, seed=False)
    admission = q.capabilities(session)
    payload = admission.payload()
    assert payload["input_support"] == {
        "instrument_policy": "EXACT_SOURCE_CATALOG",
        "resolution_mode": "PROVIDER_NATIVE",
        "bar_formation": "FIXED_DURATION",
        "alignment": "UTC_24X7",
        "closed_only": True,
        "coverage_policy": "COMPLETE_VERIFIED_WINDOW",
    }
    assert admission.fingerprint == only_canonical_fingerprint(payload)
    changed = dict(payload)
    changed["input_support"] = {**payload["input_support"], "resolution_mode": "DERIVED"}
    assert only_canonical_fingerprint(changed) != admission.fingerprint


def test_derived_seven_minute_is_refused_by_owning_plan(tmp_path, monkeypatch):
    h, q, request, session, _ = arrange(tmp_path, seed=False)
    reads = []
    monkeypatch.setattr(h.service._ranges, "read", lambda *args: reads.append(args))
    with pytest.raises(OnlyChartStudyQueryError, match="CHART_STUDY_INPUT_UNSUPPORTED"):
        q.evaluate(
            replace(
                request,
                bar_semantic=OnlyBarSemantic.fixed_duration(7),
                before_ns=request.before_ns // (7 * MINUTE_NS) * (7 * MINUTE_NS),
            ),
            session,
        )
    assert reads == []


@pytest.mark.parametrize("count", (0, 2001, True))
def test_query_input_bound_stays_exact(tmp_path, count):
    _, _, request, _, _ = arrange(tmp_path, seed=False)
    with pytest.raises(OnlyChartStudyQueryError, match="CHART_STUDY_REQUEST_INVALID"):
        replace(request, target_bar_count=count)


@pytest.mark.parametrize("shape", ("duplicate", "calendar_leaf", "calendar_missing", "calendar_wrong_grid"))
def test_native_plan_and_calendar_proof_fail_closed_before_history(tmp_path, monkeypatch, shape):
    h, q, request, session, _ = arrange(tmp_path, seed=False)
    capabilities = h.factory.bar_capabilities
    calendar = h.factory.time_bar_calendar
    if shape == "duplicate":
        monkeypatch.setattr(h.factory, "bar_capabilities", lambda *args: capabilities(*args) + capabilities(*args))
    elif shape == "calendar_leaf":
        monkeypatch.setattr(
            h.factory,
            "bar_capabilities",
            lambda *args: tuple(replace(item, calendar_fingerprint="b" * 64) for item in capabilities(*args)),
        )
    elif shape == "calendar_missing":
        monkeypatch.setattr(h.factory, "time_bar_calendar", lambda *args: None)
    else:
        monkeypatch.setattr(h.factory, "time_bar_calendar", lambda *args: replace(calendar(*args), weekend_days=(5, 6)))
    reads = []
    monkeypatch.setattr(h.service._ranges, "read", lambda *args: reads.append(args))
    with pytest.raises(OnlyChartStudyQueryError) as error:
        q.evaluate(replace(request, expected_history_projection_fingerprint="b" * 64), session)
    assert error.value.status == (400 if shape == "calendar_wrong_grid" else 503)
    assert reads == []


def test_catalog_unavailable_is_not_certified_instrument_absence(tmp_path):
    h, q, request, session, _ = arrange(tmp_path, seed=False)
    h.faults.reference_lookup = RuntimeError("unavailable secret-bearing catalog")
    with pytest.raises(OnlyChartStudyQueryError) as error:
        q.evaluate(request, session)
    assert error.value.status == 503
    assert error.value.code == "MARKET_DATA_REFERENCE_UNAVAILABLE"


@pytest.mark.parametrize("minutes", (1, 3, 5, 30, 60, 120, 240))
def test_aligned_native_request_is_not_restricted_to_fifteen_minutes(tmp_path, minutes):
    _, _, request, _, _ = arrange(tmp_path, seed=False)
    native = replace(request, bar_semantic=OnlyBarSemantic.fixed_duration(minutes))
    assert native.bar_semantic.stride_minutes == minutes
