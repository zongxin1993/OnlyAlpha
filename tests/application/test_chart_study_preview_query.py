"""Installed Chart Query with the real owning stream; controlled provider inputs, not product E2E."""

import logging
from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.application.chart_study_product_query import OnlyChartStudyProductQueryService
from onlyalpha.application.market_data_stream import OnlyMarketDataStreamProductService
from onlyalpha.application.source_read_access import OnlySourceReadAccessError
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.data.enums import OnlyMarketDataRequestStatus
from onlyalpha.data.identifiers import OnlyMarketDataSourceId
from onlyalpha.data.models import OnlyMarketDataSubscriptionResult, OnlyRealtimeBarPreviewV1
from onlyalpha.domain.market import OnlyBarType
from tests.application.test_chart_study_product_query import arrange
from tests.application.test_market_data_product import INSTRUMENT, MINUTE_NS, _FakeSource

pytestmark = pytest.mark.contract
DEFAULT_INDICATORS = {
    "atr": "3",
    "bollinger": "1",
    "ema": "1",
    "macd": "2",
    "obv": "1",
    "roc": "1",
    "rolling_return": "1",
    "rolling_volatility": "1",
    "rsi": "2",
    "sma": "1",
    "stochastic": "2",
    "vwap": "2",
    "wma": "1",
    "zscore": "1",
}


@pytest.fixture
def owned_preview(tmp_path, monkeypatch):
    harness, original, request, subject, authority = arrange(tmp_path)

    class SubscribedSource(_FakeSource):
        def subscribe(self, _request):
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, "chart-preview")

        def unsubscribe(self, _request):
            return None

    created = []

    def create(source_request):
        source = SubscribedSource(source_request, provider=harness.provider)
        created.append(source)
        return source

    # The controlled external provider is substituted; owning APIs and calculations stay real.
    monkeypatch.setattr(harness.factory, "create", create)
    streams = OnlyMarketDataStreamProductService(
        historical=harness.service,
        catalog=harness.catalog,
        fact_store=harness.service._facts,
        wal_root=harness.wal_root,
        clock=harness.service._clock,
        logger=logging.getLogger(__name__),
    )
    stream = streams.open(
        request.reference,
        instrument_id=request.instrument_id,
        bar_semantic=request.bar_semantic,
        resume_after_sequence=0,
        read_session=subject,
    )
    stream.emit_state("READY")
    preview = OnlyRealtimeBarPreviewV1(
        OnlyMarketDataSourceId("test.spot.live"),
        INSTRUMENT,
        OnlyBarType(INSTRUMENT, request.bar_semantic),
        request.before_ns,
        request.before_ns + 15 * MINUTE_NS,
        "101.00",
        "140.00",
        "90.00",
        "130.00",
        "100.00",
        request.before_ns + MINUTE_NS,
        request.before_ns + MINUTE_NS,
    )
    stream.emit_preview(preview)
    query = OnlyChartStudyProductQueryService(harness.service, original._invocation, streams)
    request = replace(request, include_unclosed_preview=True, preview_stream_id=stream.stream_id)
    try:
        yield harness, query, request, subject, authority, stream, preview, created
    finally:
        streams.close()


def _assert_same_closed(left, right):
    assert left.window == right.window
    assert left.execution is not None and right.execution is not None
    assert set(left.execution.outputs) == set(right.execution.outputs)
    for member in left.execution.outputs:
        assert left.execution.outputs[member].equals(right.execution.outputs[member])
        assert left.execution.readiness[member].states.equals(right.execution.readiness[member].states)
        assert left.execution.readiness[member].reasons.equals(right.execution.readiness[member].reasons)


def test_all_fourteen_defaults_keep_closed_values_separate_from_owning_preview(owned_preview):
    h, query, base, subject, _, stream, preview, created = owned_preview
    admissions = [admission for admission in query.capabilities(subject) if admission.support.default_variant]
    assert {
        admission.registration.type_definition.type_id.removeprefix(
            "onlyalpha.indicator."
        ): admission.registration.type_definition.semantic_version
        for admission in admissions
    } == DEFAULT_INDICATORS
    before = h.catalog.mutations, h.service._facts.writes, h.provider.sessions, h.provider.bar_fetches
    files_before = {path.relative_to(h.wal_root): path.read_bytes() for path in h.wal_root.rglob("*") if path.is_file()}
    for admission in admissions:
        registration = admission.registration
        fields = {field.name: field for field in registration.type_definition.parameters.fields}
        parameters = {
            name: Decimal(value) if fields[name].parameter_type.value == "DECIMAL" else value
            for name, value in admission.support.default_parameters.items()
        }
        request = replace(
            base,
            type_id=registration.type_definition.type_id,
            semantic_version=registration.type_definition.semantic_version,
            parameters=parameters,
            output_members=tuple(series.output_name for series in admission.support.series),
            expected_descriptor_fingerprint=only_canonical_fingerprint(registration.type_definition.descriptor()),
            expected_implementation_fingerprint=registration.implementation_manifest.implementation_fingerprint,
            expected_capability_projection_fingerprint=admission.fingerprint,
        )
        closed = query.evaluate(replace(request, include_unclosed_preview=False, preview_stream_id=None), subject)
        result = query.evaluate(request, subject)
        _assert_same_closed(closed, result)
        assert result.preview is not None, request.type_id
        assert result.preview.stream_id == stream.stream_id
        assert result.preview.bar_start_ns == result.window.resolved_end_ns == preview.bar_start_ns
        assert result.preview.bar_end_ns == preview.bar_end_ns
        assert len(result.preview.revision_fingerprint) == 64
        for member in request.output_members:
            assert len(result.execution.outputs[member]) == 25
            assert len(result.preview.execution.outputs[member]) == 1
            assert len(result.preview.execution.readiness[member].states) == 1
            assert len(result.preview.execution.readiness[member].reasons) == 1
        if request.type_id == "onlyalpha.indicator.sma":
            assert result.preview.execution.outputs["value"][0].as_py() != result.execution.outputs["value"][-1].as_py()
    assert before == (h.catalog.mutations, h.service._facts.writes, h.provider.sessions, h.provider.bar_fetches)
    assert len(created) == 1
    assert files_before == {
        path.relative_to(h.wal_root): path.read_bytes() for path in h.wal_root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("during", ["closed", "preview"])
@pytest.mark.parametrize("change", ["tick", "disconnect", "withdraw"])
def test_preview_race_discards_only_preview_while_grant_withdrawal_fails_closed(
    owned_preview, monkeypatch, during, change
):
    h, query, request, subject, authority, stream, preview, created = owned_preview
    closed = query.evaluate(replace(request, include_unclosed_preview=False, preview_stream_id=None), subject)
    original = query._invocation._execute_numeric
    calls = 0

    def execute(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == (1 if during == "closed" else 2):
            if change == "tick":
                stream.emit_preview(replace(preview, close="131.00", ts_event_ns=preview.ts_event_ns + 1))
            elif change == "disconnect":
                stream.emit_state("DEGRADED")
            else:
                authority.withdraw()
        return result

    monkeypatch.setattr(query._invocation, "_execute_numeric", execute)
    before = h.catalog.mutations, h.service._facts.writes, h.provider.sessions, h.provider.bar_fetches
    if change == "withdraw":
        with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_UNAUTHORIZED"):
            query.evaluate(request, subject)
    else:
        result = query.evaluate(request, subject)
        _assert_same_closed(closed, result)
        assert result.preview is None
    assert calls == (1 if during == "closed" else 2)
    assert before == (h.catalog.mutations, h.service._facts.writes, h.provider.sessions, h.provider.bar_fetches)
    assert len(created) == 1


@pytest.mark.parametrize("offset", [-15 * MINUTE_NS, 15 * MINUTE_NS])
def test_stream_preview_with_other_history_frontier_is_not_appended(owned_preview, offset):
    _, query, request, subject, _, stream, preview, _ = owned_preview
    stream.emit_state("DEGRADED")
    stream.emit_state("READY")
    stream.emit_preview(
        replace(
            preview,
            bar_start_ns=preview.bar_start_ns + offset,
            bar_end_ns=preview.bar_end_ns + offset,
            ts_event_ns=preview.ts_event_ns + offset,
            ts_receive_ns=preview.ts_receive_ns + offset,
        )
    )
    result = query.evaluate(request, subject)
    assert result.execution is not None
    assert len(result.execution.outputs["value"]) == 25
    assert result.preview is None
