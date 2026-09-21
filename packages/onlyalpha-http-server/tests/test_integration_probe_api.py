from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from onlyalpha_http_server.app import _install_exact_product_openapi
from onlyalpha_http_server.integrations.routes import (
    create_integration_router,
    integration_error_response,
    integration_request_validation_error_response,
)

from onlyalpha.application.integration_configuration import (
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationRevision,
)
from onlyalpha.application.integration_probe import (
    OnlyIntegrationOperationalStatus,
    OnlyIntegrationProbeAttempt,
)
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationProbeCheck,
    OnlyIntegrationProbeContractV1,
    OnlyIntegrationProbeMode,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
)
from onlyalpha.plugin.integration_probe import (
    OnlyIntegrationProbeCheckResult,
    OnlyIntegrationProbeCheckStatus,
    OnlyIntegrationProbePolicy,
    OnlyIntegrationProbeRequest,
    OnlyIntegrationProbeResult,
    OnlyIntegrationProbeStatus,
)

NOW = datetime(2026, 9, 21, tzinfo=UTC)
INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
OTHER_INTEGRATION_ID = OnlyIntegrationId("c52eb762-34cf-47d4-8cca-56ef93f0d2ac")
ATTEMPT_ID = "a52eb762-34cf-47d4-8cca-56ef93f0d2ac"


def _revision(integration_id: OnlyIntegrationId = INTEGRATION_ID) -> OnlyIntegrationRevision:
    descriptor = OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId("test.market_data"),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Test market data",
        description="Deterministic local test provider.",
        provider_id="test",
        implementation_id="test-data",
        implementation_version="1.0.0",
        public_api_version="1.1",
        capabilities=("HISTORICAL_BARS",),
        configuration_contract=OnlyIntegrationConfigurationContractV1(fields=()),
        probe_contract=OnlyIntegrationProbeContractV1(
            OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
            "TEST",
            True,
            (OnlyIntegrationProbeCheck.CONNECTIVITY,),
        ),
    )
    return OnlyIntegrationRevision.from_resolved(
        integration_id=integration_id,
        revision_sequence=1,
        type_id=descriptor.type_id.value,
        type_descriptor_fingerprint=descriptor.fingerprint,
        type_descriptor_document=descriptor.to_dict(include_fingerprint=False),
        configuration_document={},
        probe_configuration_document={"instrument": "TEST"},
        secret_bindings=(),
        created_at=NOW,
    )


def _attempt(integration_id: OnlyIntegrationId = INTEGRATION_ID) -> OnlyIntegrationProbeAttempt:
    revision = _revision(integration_id)
    request = OnlyIntegrationProbeRequest.create(
        probe_attempt_id=ATTEMPT_ID,
        integration_id=integration_id.value,
        revision=revision,
        resolved_secrets={},
        policy=OnlyIntegrationProbePolicy(),
        deadline_monotonic=10,
    )
    result = OnlyIntegrationProbeResult.create(
        request,
        probe_instrument="TEST",
        checks=(
            OnlyIntegrationProbeCheckResult(
                OnlyIntegrationProbeCheck.CONNECTIVITY,
                OnlyIntegrationProbeCheckStatus.PASS,
                3,
                observations=("HTTP reachable",),
            ),
        ),
        started_at=NOW,
        completed_at=NOW,
    )
    return OnlyIntegrationProbeAttempt.from_result(result, revision)


class _ProbeCommands:
    def __init__(self, error: str | None = None) -> None:
        self.received: list[tuple[OnlyIntegrationId, str]] = []
        self.error = error

    def probe(
        self, integration_id: OnlyIntegrationId, expected_revision_fingerprint: str
    ) -> OnlyIntegrationProbeAttempt:
        self.received.append((integration_id, expected_revision_fingerprint))
        if self.error is not None:
            raise OnlyIntegrationError(self.error, "raw provider secret must not escape")
        return _attempt()


class _ProbeQueries:
    def __init__(
        self,
        error: str | None = None,
        attempt_integration_id: OnlyIntegrationId = INTEGRATION_ID,
    ) -> None:
        self.attempt = _attempt(attempt_integration_id)
        self.error = error
        self.requested_attempt_ids: list[str] = []

    def get_operational_status(self, integration_id: OnlyIntegrationId) -> OnlyIntegrationOperationalStatus:
        if self.error is not None:
            raise OnlyIntegrationError(self.error, "raw provider secret must not escape")
        return OnlyIntegrationOperationalStatus(
            integration_id,
            self.attempt.revision_fingerprint,
            OnlyIntegrationProbeStatus.READY,
            self.attempt.probe_attempt_id,
            self.attempt.completed_at,
            True,
        )

    def list_probe_attempts(self, integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationProbeAttempt, ...]:
        assert integration_id == INTEGRATION_ID
        return (self.attempt,)

    def get_probe_attempt(self, probe_attempt_id: str) -> OnlyIntegrationProbeAttempt:
        self.requested_attempt_ids.append(probe_attempt_id)
        if probe_attempt_id != self.attempt.probe_attempt_id:
            raise OnlyIntegrationError("INTEGRATION_PROBE_ATTEMPT_NOT_FOUND")
        return self.attempt


def _client(
    commands: _ProbeCommands | None = None, queries: _ProbeQueries | None = None
) -> tuple[_ProbeCommands, TestClient]:
    probe_commands = commands or _ProbeCommands()
    app = FastAPI()
    app.include_router(
        create_integration_router(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            probe_commands,
            queries or _ProbeQueries(),
        )
    )
    app.add_exception_handler(RequestValidationError, integration_request_validation_error_response)
    app.add_exception_handler(OnlyIntegrationError, integration_error_response)
    _install_exact_product_openapi(app)
    return probe_commands, TestClient(app)


def test_probe_and_operational_reads_are_exact_and_have_no_422() -> None:
    commands, client = _client()
    path = f"/api/v2/integrations/{INTEGRATION_ID.value}"
    revision = _revision().revision_fingerprint

    probed = client.post(
        f"{path}/probe",
        json={"schema_version": 1, "expected_revision_fingerprint": revision},
    )
    assert probed.status_code == 200, probed.text
    assert probed.json()["probe_attempt_id"] == ATTEMPT_ID
    assert probed.json()["overall_status"] == "READY"
    assert commands.received == [(INTEGRATION_ID, revision)]

    status = client.get(f"{path}/operational-status")
    assert status.status_code == 200
    assert status.json() == {
        "schema_version": 1,
        "integration_id": INTEGRATION_ID.value,
        "revision_fingerprint": revision,
        "status": "READY",
        "probe_attempt_id": ATTEMPT_ID,
        "checked_at": "2026-09-21T00:00:00Z",
        "probe_supported": True,
    }
    assert client.get(f"{path}/probe-attempts").json()["items"][0]["probe_attempt_id"] == ATTEMPT_ID
    assert client.get(f"{path}/probe-attempts/{ATTEMPT_ID}").status_code == 200

    openapi = client.get("/openapi.json").json()
    assert "422" not in openapi["paths"]["/api/v2/integrations/{integration_id}/probe"]["post"]["responses"]


def test_probe_request_validation_is_strict_400() -> None:
    _, client = _client()
    response = client.post(
        f"/api/v2/integrations/{INTEGRATION_ID.value}/probe",
        json={"schema_version": 1, "expected_revision_fingerprint": "bad", "unknown": True},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INTEGRATION_REQUEST_INVALID"


@pytest.mark.parametrize(
    "attempt_id",
    (
        "abc",
        "a52eb762-34cf-17d4-8cca-56ef93f0d2ac",
        "A52EB762-34CF-47D4-8CCA-56EF93F0D2AC",
    ),
)
def test_malformed_probe_attempt_id_is_rejected_before_query(attempt_id: str) -> None:
    queries = _ProbeQueries()
    _, client = _client(queries=queries)

    response = client.get(f"/api/v2/integrations/{INTEGRATION_ID.value}/probe-attempts/{attempt_id}")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INTEGRATION_REQUEST_INVALID"
    assert queries.requested_attempt_ids == []


def test_missing_canonical_probe_attempt_id_is_not_found() -> None:
    queries = _ProbeQueries()
    missing = "f52eb762-34cf-47d4-8cca-56ef93f0d2ac"
    _, client = _client(queries=queries)

    response = client.get(f"/api/v2/integrations/{INTEGRATION_ID.value}/probe-attempts/{missing}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INTEGRATION_PROBE_ATTEMPT_NOT_FOUND"
    assert queries.requested_attempt_ids == [missing]


def test_foreign_probe_attempt_is_non_disclosing_not_found() -> None:
    queries = _ProbeQueries(attempt_integration_id=OTHER_INTEGRATION_ID)
    _, client = _client(queries=queries)

    response = client.get(f"/api/v2/integrations/{INTEGRATION_ID.value}/probe-attempts/{ATTEMPT_ID}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INTEGRATION_PROBE_ATTEMPT_NOT_FOUND"
    assert queries.requested_attempt_ids == [ATTEMPT_ID]


@pytest.mark.parametrize(
    ("code", "status"),
    (
        ("INTEGRATION_PROBE_ATTEMPT_NOT_FOUND", 404),
        ("INTEGRATION_CURRENT_REVISION_CONFLICT", 409),
        ("INTEGRATION_ARCHIVED", 409),
        ("INTEGRATION_PROBE_RESULT_CORRUPT", 500),
        ("INTEGRATION_PROBE_PROVIDER_UNAVAILABLE", 503),
        ("INTEGRATION_PROBE_PERSISTENCE_UNAVAILABLE", 503),
        ("INTEGRATION_PROBE_SECRET_UNAVAILABLE", 503),
        ("INTEGRATION_PROBE_TIMEOUT", 503),
    ),
)
def test_probe_errors_are_stable_and_sanitized(code: str, status: int) -> None:
    if code == "INTEGRATION_PROBE_ATTEMPT_NOT_FOUND":
        _, client = _client()
        response = client.get(
            f"/api/v2/integrations/{INTEGRATION_ID.value}/probe-attempts/f52eb762-34cf-47d4-8cca-56ef93f0d2ac"
        )
    else:
        _, client = _client(_ProbeCommands(code))
        response = client.post(
            f"/api/v2/integrations/{INTEGRATION_ID.value}/probe",
            json={"schema_version": 1, "expected_revision_fingerprint": _revision().revision_fingerprint},
        )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "raw provider secret" not in response.text
