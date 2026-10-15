"""Real Application/SPI under protected ASGI ingress; deterministic transport attacks."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from onlyalpha_http_server.app import create_product_app
from onlyalpha_http_server.chart_studies.routes import create_chart_study_router
from onlyalpha_http_server.chart_studies.schema import ChartStudyEvaluateRequestDto
from onlyalpha_http_server.composition import OnlyProductCalculationComposition
from onlyalpha_http_server.local_read_access import (
    CHART_CAPABILITIES_PATH,
    CHART_EVALUATE_PATH,
    OnlyLocalReadConfiguration,
    OnlyLocalReadIngress,
)
from onlyalpha_http_server.market_data.schema import MarketDataBarSemanticDto
from pydantic import ValidationError

from onlyalpha.application.integration_type_catalog import OnlyIntegrationTypeCatalog
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from tests.application.test_chart_study_numeric import composition
from tests.application.test_chart_study_product_query import arrange
from tests.application.test_source_read_access import TOKEN

ORIGIN = "http://localhost"
HEADERS = {"Authorization": "Bearer " + TOKEN, "Origin": ORIGIN}


def request_body(model):
    return dict(
        schema_version=1,
        source_reference=dict(
            integration_id=model.reference.integration_id,
            integration_revision_fingerprint=model.reference.integration_revision_fingerprint,
            expected_type_id=model.reference.expected_type_id,
        ),
        instrument_id=model.instrument_id,
        bar_semantic=MarketDataBarSemanticDto.from_model(model.bar_semantic).model_dump(mode="json"),
        window=dict(anchor_kind="BEFORE_TIME", before_ns=str(model.before_ns), target_bar_count=model.target_bar_count),
        expected_history_projection_fingerprint=model.expected_history_projection_fingerprint,
        calculation=dict(
            kind="INDICATOR",
            type_id="onlyalpha.indicator.sma",
            semantic_version="1",
            typed_parameters=dict(
                period=dict(type="INTEGER", value=model.period), price_field=dict(type="STRING", value="CLOSE")
            ),
            output_members=["value"],
            expected_descriptor_fingerprint=model.expected_descriptor_fingerprint,
            expected_implementation_fingerprint=model.expected_implementation_fingerprint,
            expected_capability_projection_fingerprint=model.expected_capability_projection_fingerprint,
        ),
        include_unclosed_preview=False,
    )


def app_for(query, authority, *, enabled=True):
    app = FastAPI()
    app.add_middleware(
        OnlyLocalReadIngress, configuration=OnlyLocalReadConfiguration(authority, ORIGIN), chart_study_enabled=enabled
    )
    app.include_router(create_chart_study_router(query))

    @app.exception_handler(RequestValidationError)
    async def invalid(_request: Request, _error: RequestValidationError):
        return JSONResponse(
            {
                "schema_version": 1,
                "error": {
                    "phase": "QUERY",
                    "code": "CHART_STUDY_REQUEST_INVALID",
                    "detail": "CHART_STUDY_REQUEST_INVALID",
                },
            },
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )

    return app


def test_authenticated_capability_and_exact_evaluation_are_no_store_and_zero_write(tmp_path):
    h, q, model, _, authority = arrange(tmp_path)
    before = h.catalog.mutations, h.service._facts.writes, h.provider.sessions
    with TestClient(app_for(q, authority), base_url=ORIGIN) as client:
        capability = client.get(CHART_CAPABILITIES_PATH, headers=HEADERS)
        assert capability.status_code == 200, capability.text
        row = capability.json()["capabilities"][0]
        assert row["capability_projection_fingerprint"] == model.expected_capability_projection_fingerprint
        result = client.post(CHART_EVALUATE_PATH, json=request_body(model), headers=HEADERS)
        assert result.status_code == 200, result.text
        assert result.headers["cache-control"] == "no-store"
        assert capability.headers["cache-control"] == "no-store"
        value = result.json()
        assert value["source_kind"] == "CHART_STUDY_TRANSIENT" and value["authority"] == "DISPLAY_ONLY"
        assert value["publication_status"] == "NOT_A_RESEARCH_RESULT"
        assert value["series"][0]["points"][0] == dict(
            time_ns=str(model.before_ns - 25 * 900_000_000_000),
            value="101.000000000000",
            readiness="PARTIAL",
            reason="WARMUP_INCOMPLETE",
            quality="CLOSED_COMPLETE",
            closed=True,
        )
        assert value["series"][0]["points"][19]["readiness"] == "READY"
    assert before == (h.catalog.mutations, h.service._facts.writes, h.provider.sessions)


@pytest.mark.parametrize("seed", (False, True))
def test_incomplete_history_and_complete_changed_http_outcomes(tmp_path, seed):
    _, q, model, _, authority = arrange(tmp_path, seed=seed)
    body = request_body(model)
    body["expected_history_projection_fingerprint"] = "b" * 64
    with TestClient(app_for(q, authority), base_url=ORIGIN) as client:
        result = client.post(CHART_EVALUATE_PATH, json=body, headers=HEADERS)
    assert result.status_code == (409 if seed else 200), result.text
    if not seed:
        assert result.json()["query_status"] == "INPUT_INCOMPLETE"
        assert result.json()["series"] == []
        assert result.json()["coverage"]["gaps"]


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), True),
        (("include_unclosed_preview",), 0),
        (("window", "target_bar_count"), True),
        (("window", "target_bar_count"), 2001),
        (("window", "before_ns"), "09223372036854775807"),
        (("window", "before_ns"), "9223372036854775808"),
        (("window", "anchor_kind"), "LATEST_CLOSED"),
        (("window", "script"), "1+1"),
        (("bar_semantic", "schema_version"), True),
        (("bar_semantic", "formation", "schema_version"), True),
        (("calculation", "typed_parameters", "period", "value"), True),
        (("calculation", "typed_parameters", "period", "value"), "20"),
        (("calculation", "typed_parameters", "price_field", "value"), "VOLUME"),
        (("calculation", "output_members"), ["value", "value"]),
        (("calculation", "type_id"), "onlyalpha.indicator.ema"),
        (("bars",), []),
    ],
)
def test_strict_server_schema_and_http_fail_before_owning_read(tmp_path, path, value, monkeypatch):
    _, q, model, _, authority = arrange(tmp_path)
    body = request_body(model)
    owner = body
    for name in path[:-1]:
        owner = owner[name]
    owner[path[-1]] = value
    with pytest.raises(ValidationError):
        ChartStudyEvaluateRequestDto.model_validate(body)
    calls = []
    monkeypatch.setattr(q, "evaluate", lambda *a: calls.append(a))
    with TestClient(app_for(q, authority), base_url=ORIGIN) as client:
        result = client.post(CHART_EVALUATE_PATH, json=body, headers=HEADERS)
    assert result.status_code == 400, result.text
    assert calls == []


@pytest.mark.parametrize(
    "method,path,headers",
    [
        ("POST", CHART_EVALUATE_PATH, {"Origin": ORIGIN}),
        ("POST", CHART_EVALUATE_PATH, {**HEADERS, "Origin": "null"}),
        ("POST", CHART_EVALUATE_PATH, {**HEADERS, "Host": "attacker.invalid"}),
        ("POST", CHART_EVALUATE_PATH, {**HEADERS, "X-User": "operator"}),
        ("POST", CHART_EVALUATE_PATH + "/", HEADERS),
        ("GET", CHART_EVALUATE_PATH, HEADERS),
        ("POST", CHART_CAPABILITIES_PATH, HEADERS),
        ("POST", "/api/v2/market-data/acquisitions", HEADERS),
        ("POST", "/api/v2/research/runs", HEADERS),
        ("POST", "/api/v2/trading/orders", HEADERS),
    ],
)
def test_exact_post_exception_does_not_open_other_routes(tmp_path, method, path, headers, monkeypatch):
    _, q, model, _, authority = arrange(tmp_path)
    calls = []
    monkeypatch.setattr(q, "evaluate", lambda *a: calls.append(a))
    with TestClient(app_for(q, authority), base_url=ORIGIN) as client:
        result = client.request(method, path, json=request_body(model), headers=headers)
    assert result.status_code == (401 if "Authorization" not in headers else 403)
    assert calls == []


def test_unadmitted_composition_remains_default_deny(tmp_path):
    _, q, model, _, authority = arrange(tmp_path)
    with TestClient(app_for(q, authority, enabled=False), base_url=ORIGIN) as client:
        assert client.get(CHART_CAPABILITIES_PATH, headers=HEADERS).status_code == 403
        assert client.post(CHART_EVALUATE_PATH, json=request_body(model), headers=HEADERS).status_code == 403


def test_duplicate_fields_nan_constants_and_oversized_bodies_never_invoke(tmp_path, monkeypatch):
    _, q, model, _, authority = arrange(tmp_path)
    calls = []
    monkeypatch.setattr(q, "evaluate", lambda *a: calls.append(a))
    payload = json.dumps(request_body(model))
    bad = [
        payload.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1),
        payload.replace('"value": 20', '"value": NaN'),
        " " * 65537,
    ]
    with TestClient(app_for(q, authority), base_url=ORIGIN) as client:
        for body in bad:
            result = client.post(
                CHART_EVALUATE_PATH, content=body, headers={**HEADERS, "Content-Type": "application/json"}
            )
            assert result.status_code == 400, result.text
    assert calls == []


def test_fragmented_request_is_cumulatively_bounded_and_disconnect_fences_actual_work(tmp_path):
    asyncio.run(_fragmented_request_disconnect(tmp_path))


async def _fragmented_request_disconnect(tmp_path):
    _, _, _, _, authority = arrange(tmp_path, seed=False)
    entered, release = asyncio.Event(), asyncio.Event()
    incoming = asyncio.Queue()
    sends = []
    seen = []

    async def application(scope, receive, send):
        seen.append(await receive())
        entered.set()
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"protected"})

    ingress = OnlyLocalReadIngress(application, OnlyLocalReadConfiguration(authority, ORIGIN), chart_study_enabled=True)
    scope = dict(
        type="http",
        method="POST",
        path=CHART_EVALUATE_PATH,
        query_string=b"",
        headers=[
            (b"host", b"localhost"),
            (b"origin", ORIGIN.encode()),
            (b"authorization", ("Bearer " + TOKEN).encode()),
            (b"content-type", b"application/json"),
            (b"content-length", b"2"),
        ],
    )

    async def send(message):
        sends.append(message)

    await incoming.put(dict(type="http.request", body=b"{", more_body=True))
    await incoming.put(dict(type="http.request", body=b"}", more_body=False))
    task = asyncio.create_task(ingress(scope, incoming.get, send))
    await entered.wait()
    assert seen == [dict(type="http.request", body=b"{}", more_body=False)]
    assert ingress._reads == 1
    await incoming.put(dict(type="http.disconnect"))
    await scope["onlyalpha.local_read_detached"].wait()
    assert ingress._reads == 1 and not task.done()
    release.set()
    await task
    assert sends == [] and ingress._reads == 0


def shipping_app(h, query, authority, composition):
    # Unused non-Chart authorities are contract fakes. The real Product factory,
    # conditional wiring and its actual validation handler remain under test.
    return create_product_app(
        reader=object(),
        product_boundary=object(),
        calculation_registry=composition.registry,
        definition_resolver=SimpleNamespace(universe_resolver=None),
        readiness_probe=object(),
        strategy_freeze=object(),
        strategy_promotion=object(),
        strategy_query=object(),
        qualification=object(),
        qualification_query=object(),
        backtest_commands=object(),
        backtest_queries=object(),
        integration_types=OnlyIntegrationTypeCatalog(OnlyDataSourceFactoryRegistry(), OnlyBrokerFactoryRegistry()),
        integration_commands=object(),
        integration_queries=object(),
        integration_probes=object(),
        integration_operational_queries=object(),
        market_data=h.service,
        local_read_configuration=OnlyLocalReadConfiguration(authority, ORIGIN),
        calculation_composition=composition,
    )


def test_shipping_product_handler_and_conditional_composition_are_real(tmp_path, monkeypatch):
    h, q, model, _, authority = arrange(tmp_path)
    invocation = q._invocation
    comp = OnlyProductCalculationComposition(invocation._registry, invocation._catalog, invocation, None)
    calls = []
    monkeypatch.setattr(h.service, "read_chart_study_history", lambda *a, **k: calls.append(a))
    with TestClient(shipping_app(h, q, authority, comp), base_url=ORIGIN) as client:
        assert client.get(CHART_CAPABILITIES_PATH, headers=HEADERS).status_code == 200
        for path, value in (("schema_version", True), ("include_unclosed_preview", 0), ("bars", [])):
            body = request_body(model)
            body[path] = value
            result = client.post(CHART_EVALUATE_PATH, json=body, headers=HEADERS)
            assert result.status_code == 400, result.text
            assert result.json()["error"]["code"] == "CHART_STUDY_REQUEST_INVALID"
            assert result.headers["cache-control"] == "no-store"
    assert calls == []


@pytest.mark.parametrize("relation", ("registry", "catalog"))
def test_transplanted_valid_invocation_does_not_enable_shipping_chart_routes(tmp_path, relation):
    h, q, model, _, authority = arrange(tmp_path)
    other, registry, catalog = composition()
    invocation = q._invocation
    comp = OnlyProductCalculationComposition(
        registry if relation == "registry" else invocation._registry,
        catalog if relation == "catalog" else invocation._catalog,
        invocation,
        None,
    )
    assert other.admission.fingerprint == invocation.admission.fingerprint
    with TestClient(shipping_app(h, q, authority, comp), base_url=ORIGIN) as client:
        assert client.get(CHART_CAPABILITIES_PATH, headers=HEADERS).status_code == 403
        assert client.post(CHART_EVALUATE_PATH, json=request_body(model), headers=HEADERS).status_code == 403


@pytest.mark.parametrize(
    "fault",
    (
        "deadline",
        "withdrawal",
        "send_cutoff",
        "caller_cancel",
        "oversize_fragment",
        "duplicate_header",
        "missing_length",
        "chunked",
    ),
)
def test_chart_framing_deadline_and_actual_work_ownership_without_sleeps(tmp_path, fault):
    asyncio.run(_transport_fault(tmp_path, fault))


async def _transport_fault(tmp_path, fault):
    from unittest.mock import patch

    from onlyalpha_http_server import local_read_access

    _, _, _, _, authority = arrange(tmp_path, seed=False)
    entered, release, unavailable, start_sent = asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
    incoming = asyncio.Queue()
    sends = []
    loop = asyncio.get_running_loop()
    actual_time = loop.time
    clock = [actual_time()]

    async def application(scope, receive, send):
        await receive()
        entered.set()
        await release.wait()
        await send(dict(type="http.response.start", status=200, headers=[]))
        await send(dict(type="http.response.body", body=b"protected"))

    async def send(message):
        sends.append(message)
        if message["type"] == "http.response.start":
            if message["status"] == 503:
                unavailable.set()
            if fault == "send_cutoff" and message["status"] == 200:
                authority.withdraw()
                start_sent.set()

    ingress = OnlyLocalReadIngress(application, OnlyLocalReadConfiguration(authority, ORIGIN), chart_study_enabled=True)
    headers = [
        (b"host", b"localhost"),
        (b"authorization", ("Bearer " + TOKEN).encode()),
        (b"content-type", b"application/json"),
        (b"content-length", b"2"),
    ]
    if fault == "duplicate_header":
        headers.append((b"content-length", b"2"))
    if fault == "missing_length":
        headers = headers[:-1]
    if fault == "chunked":
        headers.append((b"transfer-encoding", b"chunked"))
    scope = dict(type="http", method="POST", path=CHART_EVALUATE_PATH, query_string=b"", headers=headers)
    await incoming.put(
        dict(
            type="http.request",
            body=b"{}" if fault != "oversize_fragment" else b"{",
            more_body=fault == "oversize_fragment",
        )
    )
    if fault == "oversize_fragment":
        await incoming.put(dict(type="http.request", body=b"  }", more_body=False))
    with patch.object(loop, "time", side_effect=lambda: clock[0]):
        task = asyncio.create_task(ingress(scope, incoming.get, send))
        if fault in {"duplicate_header", "missing_length", "chunked", "oversize_fragment"}:
            await task
            assert not entered.is_set() and ingress._reads == 0
            assert sends[0]["status"] == (400 if fault == "oversize_fragment" else 403)
            return
        await entered.wait()
        if fault == "deadline":
            clock[0] += local_read_access.CHART_QUERY_SECONDS + 1
            loop.call_soon(lambda: None)
            await unavailable.wait()
            assert ingress._reads == 1 and not task.done()
        elif fault == "withdrawal":
            await ingress.withdraw()
        elif fault == "caller_cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert ingress._reads == 1
        release.set()
        if fault == "caller_cancel":
            await asyncio.gather(*(asyncio.shield(owner) for owner in tuple(ingress._work)))
        else:
            await task
        assert not any(message.get("body") == b"protected" for message in sends)
        assert ingress._reads == 0
        if fault == "send_cutoff":
            assert start_sent.is_set() and len(sends) == 1


def test_http_eth_native_hour_and_owning_input_support(tmp_path, monkeypatch):
    from tests.application import test_market_data_product as owner_fixture

    eth = type(owner_fixture.INSTRUMENT).parse("ETHUSDT.TEST")
    monkeypatch.setattr(owner_fixture, "INSTRUMENT", eth)
    _, query, model, _, authority = arrange(tmp_path, minutes=60, instrument=eth)
    with TestClient(app_for(query, authority), base_url=ORIGIN) as client:
        capability = client.get(CHART_CAPABILITIES_PATH, headers=HEADERS)
        assert capability.status_code == 200
        support = capability.json()["capabilities"][0]["capability_projection"]["input_support"]
        assert support["instrument_policy"] == "EXACT_SOURCE_CATALOG"
        assert support["resolution_mode"] == "PROVIDER_NATIVE"
        assert support["coverage_policy"] == "COMPLETE_VERIFIED_WINDOW"
        result = client.post(CHART_EVALUATE_PATH, json=request_body(model), headers=HEADERS)
        assert result.status_code == 200, result.text
        response = result.json()
        assert response["input"]["resolved_start_ns"] == str(model.before_ns - 25 * 60 * owner_fixture.MINUTE_NS)
        assert response["series"][0]["points"][19]["readiness"] == "READY"


def test_future_window_readiness_survives_application_and_protected_evaluate_http(tmp_path, monkeypatch):
    h, q, model, _, authority = arrange(tmp_path)
    before = h.catalog.mutations, h.service._facts.writes, h.provider.sessions
    now = model.before_ns - 3_800_000_000
    monkeypatch.setattr(h.service._clock, "timestamp_ns", lambda: now)
    application = app_for(q, authority)
    with TestClient(application, base_url=ORIGIN) as client:
        result = client.post(CHART_EVALUATE_PATH, json=request_body(model), headers=HEADERS)
        assert result.status_code == 503, result.text
        assert result.json()["error"]["code"] == "MARKET_DATA_WINDOW_NOT_CLOSED"
        assert result.headers["Retry-After"] == "4"
        assert result.headers["Cache-Control"] == "no-store"
        now = model.before_ns
        recovered = client.post(CHART_EVALUATE_PATH, json=request_body(model), headers=HEADERS)
        assert recovered.status_code == 200, recovered.text
        assert "Retry-After" not in recovered.headers
    assert before == (h.catalog.mutations, h.service._facts.writes, h.provider.sessions)
    document = application.openapi()
    assert (
        document["paths"][CHART_EVALUATE_PATH]["post"]["responses"]["503"]["headers"]["Retry-After"]["schema"][
            "pattern"
        ]
        == "^[1-9][0-9]*$"
    )
    assert "headers" not in document["paths"][CHART_CAPABILITIES_PATH]["get"]["responses"]["503"]
