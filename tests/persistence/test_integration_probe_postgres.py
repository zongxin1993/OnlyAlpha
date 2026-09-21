from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from onlyalpha.application.integration_configuration import (
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationRevision,
)
from onlyalpha.application.integration_probe import OnlyIntegrationProbeAttempt
from onlyalpha.persistence.postgres.integration_probe_store import OnlyPostgresIntegrationProbeStore
from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore
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
)

pytestmark = pytest.mark.postgres
NOW = datetime(2026, 9, 21, tzinfo=UTC)
INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")


def _descriptor() -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
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


def _seed_revision(postgres_dsn: str) -> OnlyIntegrationRevision:
    descriptor = _descriptor()
    revision = OnlyIntegrationRevision.from_resolved(
        integration_id=INTEGRATION_ID,
        revision_sequence=1,
        type_id=descriptor.type_id.value,
        type_descriptor_fingerprint=descriptor.fingerprint,
        type_descriptor_document=descriptor.to_dict(include_fingerprint=False),
        configuration_document={"timeout_seconds": 3},
        probe_configuration_document={"instrument": "TEST"},
        secret_bindings=(),
        created_at=NOW,
    )
    state = OnlyPostgresIntegrationStore(postgres_dsn, now=lambda: NOW)
    state.create_integration(INTEGRATION_ID, descriptor.type_id, "Test source")
    state.insert_revision(revision, ())
    state.set_current_revision(INTEGRATION_ID, revision.revision_fingerprint)
    return revision


def _attempt(revision: OnlyIntegrationRevision, attempt_id: str, completed_at: datetime) -> OnlyIntegrationProbeAttempt:
    request = OnlyIntegrationProbeRequest.create(
        probe_attempt_id=attempt_id,
        integration_id=INTEGRATION_ID.value,
        revision=revision,
        resolved_secrets={"token": "never-persist-this"},
        policy=OnlyIntegrationProbePolicy(),
        deadline_monotonic=10.0,
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
        started_at=completed_at - timedelta(milliseconds=3),
        completed_at=completed_at,
    )
    return OnlyIntegrationProbeAttempt.from_result(result, revision)


def test_probe_attempt_round_trip_latest_order_and_plaintext_absence(postgres_dsn: str) -> None:
    revision = _seed_revision(postgres_dsn)
    store = OnlyPostgresIntegrationProbeStore(postgres_dsn)
    first = _attempt(revision, "152eb762-34cf-47d4-8cca-56ef93f0d2ac", NOW + timedelta(seconds=1))
    later_low_id = _attempt(revision, "252eb762-34cf-47d4-8cca-56ef93f0d2ac", NOW + timedelta(seconds=2))
    later_high_id = _attempt(revision, "f52eb762-34cf-47d4-8cca-56ef93f0d2ac", NOW + timedelta(seconds=2))

    for attempt in (first, later_low_id, later_high_id):
        store.insert_probe_attempt(attempt)

    assert store.get_probe_attempt(first.probe_attempt_id) == first
    assert store.list_probe_attempts(INTEGRATION_ID) == (later_high_id, later_low_id, first)
    assert store.latest_probe_attempt(INTEGRATION_ID, revision.revision_fingerprint) == later_high_id
    with psycopg.connect(postgres_dsn) as connection:
        dumped = connection.execute(
            "SELECT result_document::text FROM integration_probe_attempt WHERE probe_attempt_id = %s",
            (first.probe_attempt_id,),
        ).fetchone()[0]
    assert "never-persist-this" not in dumped


def test_probe_attempt_is_database_immutable(postgres_dsn: str) -> None:
    revision = _seed_revision(postgres_dsn)
    attempt = _attempt(revision, "152eb762-34cf-47d4-8cca-56ef93f0d2ac", NOW)
    OnlyPostgresIntegrationProbeStore(postgres_dsn).insert_probe_attempt(attempt)

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.DatabaseError):
        connection.execute(
            "UPDATE integration_probe_attempt SET overall_status = 'FAILED' WHERE probe_attempt_id = %s",
            (attempt.probe_attempt_id,),
        )


def test_probe_result_fingerprint_corruption_fails_closed(postgres_dsn: str) -> None:
    revision = _seed_revision(postgres_dsn)
    attempt = _attempt(revision, "152eb762-34cf-47d4-8cca-56ef93f0d2ac", NOW)
    OnlyPostgresIntegrationProbeStore(postgres_dsn).insert_probe_attempt(attempt)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("ALTER TABLE integration_probe_attempt DISABLE TRIGGER USER")
        connection.execute(
            "UPDATE integration_probe_attempt SET result_fingerprint = %s WHERE probe_attempt_id = %s",
            ("f" * 64, attempt.probe_attempt_id),
        )
        connection.execute("ALTER TABLE integration_probe_attempt ENABLE TRIGGER USER")

    with pytest.raises(OnlyIntegrationError) as corrupt:
        OnlyPostgresIntegrationProbeStore(postgres_dsn).get_probe_attempt(attempt.probe_attempt_id)
    assert corrupt.value.code == "INTEGRATION_PROBE_RESULT_CORRUPT"


def test_probe_attempt_lookup_is_exact(postgres_dsn: str) -> None:
    store = OnlyPostgresIntegrationProbeStore(postgres_dsn)
    with pytest.raises(OnlyIntegrationError) as missing:
        store.get_probe_attempt("152eb762-34cf-47d4-8cca-56ef93f0d2ac")
    assert missing.value.code == "INTEGRATION_PROBE_ATTEMPT_NOT_FOUND"
    assert store.latest_probe_attempt(INTEGRATION_ID, "f" * 64) is None
    assert store.list_probe_attempts(INTEGRATION_ID) == ()
