from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.dev_web import DEV_COOKIE, OnlyDevWebIngress, only_dev_web_configuration
from onlyalpha_http_server.watchlists.routes import create_watchlist_router

from onlyalpha.application.watchlists import OnlyWatchlistBook

ORIGIN = "http://127.0.0.1:5173"


class Service:
    def __init__(self):
        self.saved = []

    def read(self):
        return OnlyWatchlistBook(0, ())

    def save(self, command_id, expected_version, lists, session):
        session.check_active()
        self.saved.append((command_id, expected_version, lists))
        return OnlyWatchlistBook(1, lists)


def test_only_explicit_dev_owner_policy_authorizes_watchlist_writes():
    service = Service()
    app = FastAPI()
    app.include_router(create_watchlist_router(service))
    configuration, credential = only_dev_web_configuration(ORIGIN, ())
    app.add_middleware(OnlyDevWebIngress, configuration=configuration)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(DEV_COOKIE, credential)
        assert client.get("/api/v2/watchlists").status_code == 200
        payload = {
            "schema_version": 2,
            "command_id": "0926c6a2-0cb8-47a5-8d94-cdb89b336182",
            "expected_version": 0,
            "lists": [],
        }
        assert client.put("/api/v2/watchlists", json=payload).status_code == 403
        assert (
            client.put("/api/v2/watchlists", json=payload, headers={"Origin": "http://attacker.test"}).status_code
            == 403
        )
        response = client.put("/api/v2/watchlists", json=payload, headers={"Origin": ORIGIN})
        assert response.status_code == 200 and response.json()["version"] == 1
        assert len(service.saved) == 1


def test_read_only_ingress_cannot_be_promoted_to_watchlist_owner():
    from onlyalpha_http_server.local_read_access import OnlyLocalReadIngress

    service = Service()
    app = FastAPI()
    app.include_router(create_watchlist_router(service))
    configuration, credential = only_dev_web_configuration(ORIGIN, ())
    app.add_middleware(OnlyLocalReadIngress, configuration=configuration)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = {"Origin": ORIGIN, "Authorization": "Bearer " + credential}
        assert client.get("/api/v2/watchlists", headers=headers).status_code == 403
        assert client.put("/api/v2/watchlists", json={}, headers=headers).status_code == 403
        assert service.saved == []


def test_duplicate_json_keys_are_rejected_before_owner_command_admission():
    service = Service()
    app = FastAPI()
    app.include_router(create_watchlist_router(service))
    configuration, credential = only_dev_web_configuration(ORIGIN, ())
    app.add_middleware(OnlyDevWebIngress, configuration=configuration)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(DEV_COOKIE, credential)
        response = client.put(
            "/api/v2/watchlists",
            content='{"expected_version":0,"expected_version":1}',
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        )
        assert response.status_code == 403
        assert service.saved == []


def test_member_sources_roundtrip_and_old_wire_shape_is_rejected():
    service = Service()
    app = FastAPI()
    app.include_router(create_watchlist_router(service))
    configuration, credential = only_dev_web_configuration(ORIGIN, ())
    app.add_middleware(OnlyDevWebIngress, configuration=configuration)
    source = {
        "integration_id": "source",
        "integration_revision_fingerprint": "a" * 64,
        "expected_type_id": "test.market_data",
    }
    members = [
        {"source": source, "instrument_id": "BTCUSDT.BINANCE"},
        {"source": {**source, "integration_id": "other"}, "instrument_id": "BTCUSDT.BINANCE"},
    ]
    payload = {
        "schema_version": 2,
        "command_id": "0926c6a2-0cb8-47a5-8d94-cdb89b336182",
        "expected_version": 0,
        "lists": [{"list_id": "f496366a-fb58-4d25-b822-872317f216f4", "name": "混合", "members": members}],
    }
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(DEV_COOKIE, credential)
        response = client.put("/api/v2/watchlists", json=payload, headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert response.json()["schema_version"] == 2
        assert response.json()["lists"][0]["members"] == members
        assert (
            client.put(
                "/api/v2/watchlists", json={**payload, "schema_version": 1}, headers={"Origin": ORIGIN}
            ).status_code
            == 422
        )
        old_list = {
            "list_id": payload["lists"][0]["list_id"],
            "name": "旧",
            "source": source,
            "instrument_ids": ["BTCUSDT.BINANCE"],
        }
        assert (
            client.put(
                "/api/v2/watchlists", json={**payload, "lists": [old_list]}, headers={"Origin": ORIGIN}
            ).status_code
            == 422
        )
        assert len(service.saved) == 1
