from __future__ import annotations

from typing import cast

import psycopg
import pytest

from onlyalpha.application.integration_configuration import OnlyIntegrationError, OnlyIntegrationId
from onlyalpha.application.integration_probe import OnlyIntegrationProbeAttempt
from onlyalpha.persistence.postgres.integration_probe_store import OnlyPostgresIntegrationProbeStore


@pytest.mark.parametrize("operation", ("insert", "get", "list", "latest"))
def test_probe_store_database_errors_are_persistence_failures(monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise psycopg.OperationalError("offline")

    monkeypatch.setattr(psycopg, "connect", unavailable)
    store = OnlyPostgresIntegrationProbeStore("postgresql://unused")
    integration_id = OnlyIntegrationId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

    with pytest.raises(OnlyIntegrationError) as raised:
        if operation == "insert":
            store.insert_probe_attempt(cast(OnlyIntegrationProbeAttempt, object()))
        elif operation == "get":
            store.get_probe_attempt("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        elif operation == "list":
            store.list_probe_attempts(integration_id)
        else:
            store.latest_probe_attempt(integration_id, "a" * 64)

    assert raised.value.code == "INTEGRATION_PROBE_PERSISTENCE_UNAVAILABLE"
