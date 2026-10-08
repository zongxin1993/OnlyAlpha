"""Dev seed admission, operator preservation and exact Product response proofs."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import pytest

from scripts.product_acceptance_client import AcceptanceFailure, ProductHttpClient
from scripts.provision_dev_market_data import (
    CREATE_COMMAND_ID,
    INTEGRATION_ID,
    PUBLISH_COMMAND_ID,
    TYPE_ID,
    provision,
)

REVISION = "a" * 64
OTHER_ID = "00000000-0000-4000-8000-000000000101"
SOURCE = {
    "integration_id": INTEGRATION_ID,
    "integration_revision_fingerprint": REVISION,
    "type_id": TYPE_ID,
    "source_id": "server-canonical-source",
    "environment": "GLOBAL",
}
SEED = {
    "integration_id": INTEGRATION_ID,
    "type_id": TYPE_ID,
    "lifecycle_state": "ACTIVE",
    "current_revision_fingerprint": None,
    "draft_version": 1,
}


class _Client(ProductHttpClient):
    def __init__(self) -> None:
        super().__init__("http://product.test")
        self.sources: list[dict[str, Any]] = []
        self.integrations: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str, object, str | None]] = []
        self.created: dict[str, Any] = {
            "schema_version": 1,
            "integration_id": INTEGRATION_ID,
            "command_id": CREATE_COMMAND_ID,
            "outcome_kind": "INTEGRATION",
            "outcome_id": INTEGRATION_ID,
        }
        self.published = {
            **self.created,
            "command_id": PUBLISH_COMMAND_ID,
            "outcome_kind": "INTEGRATION_REVISION",
            "outcome_id": REVISION,
        }
        self.published_source = deepcopy(SOURCE)
        self.fail_after_commit: str | None = None

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        self.calls.append((method, path, payload, idempotency_key))
        if method == "GET" and path == "/api/v2/market-data/sources":
            return {"schema_version": 1, "sources": deepcopy(self.sources)}
        if method == "GET" and path == "/api/v2/integrations":
            return {"items": deepcopy(self.integrations)}
        if method == "POST" and path == "/api/v2/integrations":
            assert expected_status == 201 and idempotency_key == CREATE_COMMAND_ID
            assert payload == {
                "schema_version": 1,
                "integration_id": INTEGRATION_ID,
                "type_id": TYPE_ID,
                "display_name": "Binance Spot Market Data",
            }
            if not self.integrations:
                self.integrations = [deepcopy(SEED)]
            response = self.created
        elif method == "POST" and path == f"/api/v2/integrations/{INTEGRATION_ID}/revisions":
            assert expected_status == 200 and idempotency_key == PUBLISH_COMMAND_ID
            assert payload == {"schema_version": 1, "expected_draft_version": 1}
            self.integrations[0]["current_revision_fingerprint"] = REVISION
            self.sources = [deepcopy(self.published_source)]
            response = self.published
        else:
            raise AssertionError((method, path))
        if self.fail_after_commit == path:
            self.fail_after_commit = None
            raise ConnectionError("response lost after durable commit")
        return deepcopy(response)


def test_empty_dev_stack_publishes_defaults_and_reuses_server_source() -> None:
    client = _Client()
    assert provision(client) == {
        "provisioning": "PUBLISHED",
        "integration_id": INTEGRATION_ID,
        "revision_fingerprint": REVISION,
        "source_id": SOURCE["source_id"],
    }
    first_calls = list(client.calls)
    assert provision(client) == {"provisioning": "EXISTING_SOURCE", "source_count": 1}
    assert client.calls[len(first_calls) :] == [("GET", "/api/v2/market-data/sources", None, None)]
    assert [call[0] for call in first_calls] == ["GET", "GET", "POST", "POST", "GET"]


@pytest.mark.parametrize("path", ["/api/v2/integrations", f"/api/v2/integrations/{INTEGRATION_ID}/revisions"])
def test_unknown_response_resumes_same_identity_without_second_source(path: str) -> None:
    client = _Client()
    client.fail_after_commit = path
    with pytest.raises(ConnectionError, match="durable commit"):
        provision(client)
    assert provision(client)["provisioning"] in {"PUBLISHED", "EXISTING_SOURCE"}
    assert client.integrations == [{**SEED, "current_revision_fingerprint": REVISION}]
    assert client.sources == [SOURCE]
    commands = [call[3] for call in client.calls if call[0] == "POST"]
    assert set(commands) == {CREATE_COMMAND_ID, PUBLISH_COMMAND_ID}


@pytest.mark.parametrize(
    "sources", [[{**SOURCE, "integration_id": OTHER_ID}], [SOURCE, {**SOURCE, "integration_id": OTHER_ID}]]
)
def test_existing_and_ambiguous_live_sources_are_not_replaced(sources: list[dict[str, Any]]) -> None:
    client = _Client()
    client.sources = sources
    assert provision(client) == {"provisioning": "EXISTING_SOURCE", "source_count": len(sources)}
    assert all(call[0] == "GET" for call in client.calls)


@pytest.mark.parametrize(
    "changes",
    [
        {"lifecycle_state": "DISABLED"},
        {"lifecycle_state": "ARCHIVED"},
        {"draft_version": 2},
        {"current_revision_fingerprint": REVISION},
    ],
)
def test_operator_decisions_are_preserved_without_commands(changes: dict[str, Any]) -> None:
    client = _Client()
    client.integrations = [{**SEED, **changes}]
    assert provision(client) == {"provisioning": "PRESERVED", "integration_id": INTEGRATION_ID}
    assert all(call[0] == "GET" for call in client.calls)


@pytest.mark.parametrize(
    "changes",
    [
        {"integration_id": "wrong-owner"},
        {"integration_revision_fingerprint": None},
        {"source_id": None},
        {"type_id": None},
        {"environment": None},
    ],
)
def test_incomplete_source_proof_never_means_absence(changes: dict[str, Any]) -> None:
    client = _Client()
    client.sources = [{**SOURCE, **changes}]
    with pytest.raises(AcceptanceFailure, match="SOURCE_PROOF_INVALID"):
        provision(client)
    assert all(call[0] == "GET" for call in client.calls)


def test_duplicate_source_owner_fails_closed() -> None:
    client = _Client()
    client.sources = [SOURCE, {**SOURCE, "integration_revision_fingerprint": "b" * 64}]
    with pytest.raises(AcceptanceFailure, match="SOURCE_PROOF_INVALID"):
        provision(client)
    assert all(call[0] == "GET" for call in client.calls)


@pytest.mark.parametrize(
    "changes",
    [
        {"type_id": "binance.spot.broker"},
        {"lifecycle_state": "UNKNOWN"},
        {"current_revision_fingerprint": "broken"},
        {"draft_version": None},
    ],
)
def test_invalid_seed_proof_cannot_admit_publish(changes: dict[str, Any]) -> None:
    client = _Client()
    client.integrations = [{**SEED, **changes}]
    with pytest.raises(AcceptanceFailure, match="INTEGRATION_PROOF_INVALID"):
        provision(client)
    assert all(call[0] == "GET" for call in client.calls)


@pytest.mark.parametrize(
    "changes",
    [
        {"integration_id": OTHER_ID},
        {"integration_revision_fingerprint": "b" * 64},
        {"type_id": "binance.spot.broker"},
        {"environment": "SPOT_TESTNET"},
    ],
)
def test_publication_postcondition_requires_exact_owner_revision_and_family(changes: dict[str, Any]) -> None:
    client = _Client()
    client.published_source.update(changes)
    with pytest.raises(AcceptanceFailure, match="PUBLISHED_SOURCE_UNAVAILABLE"):
        provision(client)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"schema_version": 1},
        {"schema_version": 1, "sources": None},
        {"schema_version": 1, "sources": [None]},
        {"schema_version": True, "sources": []},
        {"schema_version": 1.0, "sources": []},
    ],
)
def test_unavailable_or_malformed_catalog_never_admits_create(
    response: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _Client()
    monkeypatch.setattr(client, "request", lambda *args, **kwargs: response)
    with pytest.raises(AcceptanceFailure, match="RESPONSE_INVALID"):
        provision(client)


def test_source_query_failure_is_not_reinterpreted_as_no_source(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()

    def unavailable(*args: object, **kwargs: object) -> dict[str, Any]:
        raise AcceptanceFailure("503 Product authority unavailable")

    monkeypatch.setattr(client, "request", unavailable)
    with pytest.raises(AcceptanceFailure, match="authority unavailable"):
        provision(client)


@pytest.mark.parametrize("response_name", ["created", "published"])
@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"command_id": OTHER_ID},
        {"integration_id": OTHER_ID},
        {"outcome_kind": "ORDER"},
        {"outcome_id": None},
    ],
)
def test_wrong_command_or_owner_proof_never_reports_publication(
    response_name: str,
    changes: dict[str, Any],
) -> None:
    client = _Client()
    getattr(client, response_name).update(changes)
    with pytest.raises(AcceptanceFailure, match="COMMAND_PROOF_INVALID"):
        provision(client)
    if response_name == "created":
        assert len([call for call in client.calls if call[0] == "POST"]) == 1


@pytest.mark.parametrize(
    "records",
    [
        [SEED, SEED],
        [{**SEED, "integration_id": None}],
        [{key: value for key, value in SEED.items() if key != "current_revision_fingerprint"}],
    ],
)
def test_missing_or_duplicate_integration_proof_never_admits_command(records: list[dict[str, Any]]) -> None:
    client = _Client()
    client.integrations = records
    with pytest.raises(AcceptanceFailure, match="INTEGRATION_PROOF_INVALID"):
        provision(client)
    assert all(call[0] == "GET" for call in client.calls)
