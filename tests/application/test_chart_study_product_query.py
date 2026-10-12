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


def arrange(tmp_path, *, period=20, seed=True):
    harness = _service(tmp_path, native_minutes=(1, 15))
    reference = _reference(harness.revision_fingerprint)
    authority = _authority(reference)
    session = authority.authenticate("Bearer " + TOKEN)
    end = OnlyTimestamp.from_datetime(BASE).unix_nanos
    count = 25
    if seed:
        harness.service.acquire_bars(
            reference,
            instrument_id=str(INSTRUMENT),
            start_ns=end - count * 15 * MINUTE_NS,
            end_ns=end,
            bar_semantic=SEMANTIC,
        )
    invocation, _, _ = composition()
    query = OnlyChartStudyProductQueryService(harness.service, invocation, supported_instrument_ids=(str(INSTRUMENT),))
    admission = query.capabilities(session)
    window = harness.service.query_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        anchor_kind=OnlyBarWindowAnchorKind.BEFORE_TIME,
        before_ns=end,
        target_bar_count=count,
        bar_semantic=SEMANTIC,
        read_session=session,
    )
    request = OnlyChartStudyRequestV1(
        reference,
        str(INSTRUMENT),
        SEMANTIC,
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
    "shape,expected", (("empty", 404), ("duplicate", 503), ("wrong_family", 503), ("wrong_owner", 503))
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
