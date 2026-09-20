from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import psycopg
import pytest

from onlyalpha.application.integration_configuration import (
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.persistence.postgres import (
    DEFAULT_MIGRATION_ROOT,
    MASTER_KEY_BYTES,
    OnlyPostgresCredentialAuthority,
    OnlyPostgresIntegrationStore,
)
from onlyalpha.persistence.postgres.credentials import OnlyCredentialError
from onlyalpha.persistence.postgres.integration_store import OnlyIntegrationPutDisposition
from onlyalpha.persistence.postgres.migration import (
    OnlyPostgresMigrationAuthority,
    OnlyPostgresMigrationIntegrityError,
)
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationConfigurationFieldV1,
    OnlyIntegrationProbeCheck,
    OnlyIntegrationProbeContractV1,
    OnlyIntegrationProbeMode,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
    OnlyIntegrationValueKind,
)

pytestmark = pytest.mark.postgres
NOW = datetime(2026, 9, 20, tzinfo=UTC)


def _descriptor() -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId("binance.spot.market_data"),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Binance Spot Market Data",
        description="Binance Spot market-data access.",
        provider_id="binance",
        implementation_id="binance",
        implementation_version="1.0.0",
        public_api_version="1.1",
        capabilities=("HISTORICAL_BARS",),
        configuration_contract=OnlyIntegrationConfigurationContractV1(
            fields=(
                OnlyIntegrationConfigurationFieldV1(
                    "api_key",
                    OnlyIntegrationValueKind.STRING,
                    required=True,
                    secret=True,
                    display_name="API key",
                ),
                OnlyIntegrationConfigurationFieldV1(
                    "timeout_seconds",
                    OnlyIntegrationValueKind.DURATION,
                    required=False,
                    default=10,
                    display_name="Timeout",
                ),
            )
        ),
        probe_contract=OnlyIntegrationProbeContractV1(
            OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
            "BTCUSDT",
            True,
            (OnlyIntegrationProbeCheck.REFERENCE_DATA,),
        ),
    )


def _seed(postgres_dsn: str) -> tuple[OnlyPostgresIntegrationStore, OnlyIntegrationId]:
    store = OnlyPostgresIntegrationStore(postgres_dsn, now=lambda: NOW)
    integration_id = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
    store.create_integration(integration_id, _descriptor().type_id, "Primary Binance")
    return store, integration_id


def test_integration_identity_type_and_one_draft_are_durable(postgres_dsn: str) -> None:
    store, integration_id = _seed(postgres_dsn)
    draft = store.create_draft(
        integration_id,
        _descriptor(),
        {"timeout_seconds": 12},
        {"instrument": "BTCUSDT"},
    )

    assert store.load_integration(integration_id).display_name == "Primary Binance"
    assert store.load_draft(integration_id) == draft
    with pytest.raises(OnlyIntegrationError) as duplicate:
        store.create_draft(integration_id, _descriptor(), {}, None)
    assert duplicate.value.code == "INTEGRATION_PERSISTENCE_CONFLICT"

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.DatabaseError):
        connection.execute(
            "UPDATE integration SET type_id = 'tushare.market_data' WHERE integration_id = %s",
            (integration_id.value,),
        )


def test_draft_cas_across_connections_has_one_winner(postgres_dsn: str) -> None:
    store, integration_id = _seed(postgres_dsn)
    store.create_draft(integration_id, _descriptor(), {"timeout_seconds": 10}, None)

    def update(timeout: int) -> object:
        try:
            return OnlyPostgresIntegrationStore(postgres_dsn, now=lambda: NOW).update_draft(
                integration_id,
                1,
                _descriptor(),
                {"timeout_seconds": timeout},
                None,
            )
        except OnlyIntegrationError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(update, (20, 30)))

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    conflicts = tuple(item for item in outcomes if isinstance(item, OnlyIntegrationError))
    assert len(conflicts) == 1 and conflicts[0].code == "INTEGRATION_DRAFT_VERSION_CONFLICT"
    assert store.load_draft(integration_id).draft_version == 2


def test_draft_binding_validates_slot_owner_field_and_generation(postgres_dsn: str) -> None:
    store, integration_id = _seed(postgres_dsn)
    store.create_draft(integration_id, _descriptor(), {}, None)
    credential = OnlyPostgresCredentialAuthority(postgres_dsn, b"k" * MASTER_KEY_BYTES).create(
        "INTEGRATION_SECRET", integration_id.value, "api_key", "secret"
    )
    binding = OnlyIntegrationSecretBinding("api_key", credential.credential_id, credential.generation)

    updated = store.replace_draft_secret_bindings(integration_id, 1, (binding,))

    assert updated.draft_version == 2
    assert store.load_draft_secret_bindings(integration_id) == (binding,)
    with psycopg.connect(postgres_dsn, row_factory=psycopg.rows.dict_row) as connection:
        row = connection.execute("SELECT * FROM integration_draft_secret_binding").fetchone()
    assert row is not None and set(row) == {
        "integration_id",
        "field_id",
        "credential_id",
        "credential_generation",
    }

    other = OnlyPostgresCredentialAuthority(postgres_dsn, b"k" * MASTER_KEY_BYTES).create(
        "INTEGRATION_SECRET", "672e3601-506f-45ea-ad7e-452e36f548ea", "api_key", "other"
    )
    with pytest.raises(OnlyIntegrationError) as invalid:
        store.replace_draft_secret_bindings(
            integration_id,
            2,
            (OnlyIntegrationSecretBinding("api_key", other.credential_id, 1),),
        )
    assert invalid.value.code == "INTEGRATION_SECRET_BINDING_INVALID"


def test_revision_insert_is_convergent_immutable_and_detects_corruption(postgres_dsn: str) -> None:
    store, integration_id = _seed(postgres_dsn)
    draft = store.create_draft(integration_id, _descriptor(), {"timeout_seconds": 12}, None)
    credential = OnlyPostgresCredentialAuthority(postgres_dsn, b"k" * MASTER_KEY_BYTES).create(
        "INTEGRATION_SECRET", integration_id.value, "api_key", "secret"
    )
    binding = OnlyIntegrationSecretBinding("api_key", credential.credential_id, 1)
    revision = OnlyIntegrationRevision.from_draft(draft, 1, "a" * 64, (binding,), NOW)

    assert store.insert_revision(revision, (binding,)) is OnlyIntegrationPutDisposition.CREATED
    assert store.insert_revision(revision, (binding,)) is OnlyIntegrationPutDisposition.REUSED
    retry = replace(revision, revision_sequence=99, created_at=datetime(2026, 9, 21, tzinfo=UTC))
    assert retry.revision_fingerprint == revision.revision_fingerprint
    assert store.insert_revision(retry, (binding,)) is OnlyIntegrationPutDisposition.REUSED
    assert store.load_revision(revision.revision_fingerprint) == revision
    assert store.list_revision_history(integration_id) == (revision,)
    assert store.load_revision_secret_bindings(revision.revision_fingerprint) == (binding,)

    corrupted = replace(revision, configuration_document={"timeout_seconds": 99})
    with pytest.raises(OnlyIntegrationError) as raised:
        store.insert_revision(corrupted, (binding,))
    assert raised.value.code == "INTEGRATION_REVISION_CORRUPT"

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.DatabaseError):
        connection.execute(
            "UPDATE integration_revision_secret_binding SET credential_generation = 2 WHERE revision_fingerprint = %s",
            (revision.revision_fingerprint,),
        )
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.DatabaseError):
        connection.execute(
            "UPDATE integration_revision SET runtime_configuration_fingerprint = %s WHERE revision_fingerprint = %s",
            ("b" * 64, revision.revision_fingerprint),
        )


@pytest.mark.parametrize("value", [1e20, -0.0])
def test_json_number_identity_survives_draft_and_revision_round_trip(postgres_dsn: str, value: float) -> None:
    store, integration_id = _seed(postgres_dsn)
    draft = store.create_draft(integration_id, _descriptor(), {"timeout_seconds": value}, None)

    assert store.load_draft(integration_id) == draft
    revision = OnlyIntegrationRevision.from_draft(draft, 1, "a" * 64, (), NOW)
    assert store.insert_revision(revision, ()) is OnlyIntegrationPutDisposition.CREATED
    assert store.load_revision(revision.revision_fingerprint) == revision


def test_old_revision_generation_never_resolves_rotated_secret(postgres_dsn: str) -> None:
    store, integration_id = _seed(postgres_dsn)
    draft = store.create_draft(integration_id, _descriptor(), {}, None)
    credentials = OnlyPostgresCredentialAuthority(postgres_dsn, b"k" * MASTER_KEY_BYTES)
    credential = credentials.create("INTEGRATION_SECRET", integration_id.value, "api_key", "old")
    binding = OnlyIntegrationSecretBinding("api_key", credential.credential_id, 1)
    revision = OnlyIntegrationRevision.from_draft(draft, 1, "a" * 64, (binding,), NOW)
    store.insert_revision(revision, (binding,))

    credentials.rotate(credential.credential_id, 1, "new")

    persisted = store.load_revision_secret_bindings(revision.revision_fingerprint)[0]
    assert persisted.credential_generation == 1
    assert store.insert_revision(revision, (binding,)) is OnlyIntegrationPutDisposition.REUSED
    with pytest.raises(OnlyCredentialError) as mismatch:
        credentials.read_secret(persisted.credential_id, persisted.credential_generation)
    assert mismatch.value.code == "CREDENTIAL_GENERATION_MISMATCH"


def test_transaction_boundary_rolls_back_revision_and_pointer_together(postgres_dsn: str) -> None:
    store, integration_id = _seed(postgres_dsn)
    draft = store.create_draft(integration_id, _descriptor(), {}, None)
    revision = OnlyIntegrationRevision.from_draft(draft, 1, "a" * 64, (), NOW)

    with pytest.raises(RuntimeError, match="injected"):
        with store.transaction() as transaction:
            transaction.insert_revision(revision, ())
            transaction.set_current_revision(integration_id, revision.revision_fingerprint)
            raise RuntimeError("injected")

    assert store.load_integration(integration_id).current_revision_fingerprint is None
    with pytest.raises(OnlyIntegrationError) as missing:
        store.load_revision(revision.revision_fingerprint)
    assert missing.value.code == "INTEGRATION_REVISION_NOT_FOUND"


def test_revision_sequence_conflict_has_one_database_winner(postgres_dsn: str) -> None:
    store, integration_id = _seed(postgres_dsn)
    draft = store.create_draft(integration_id, _descriptor(), {}, None)
    revisions = (
        OnlyIntegrationRevision.from_draft(draft, 1, "a" * 64, (), NOW),
        OnlyIntegrationRevision.from_draft(draft, 1, "b" * 64, (), NOW),
    )

    def insert(revision: OnlyIntegrationRevision) -> object:
        try:
            return OnlyPostgresIntegrationStore(postgres_dsn, now=lambda: NOW).insert_revision(revision, ())
        except OnlyIntegrationError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(insert, revisions))

    assert sum(item is OnlyIntegrationPutDisposition.CREATED for item in outcomes) == 1
    assert sum(isinstance(item, OnlyIntegrationError) for item in outcomes) == 1
    assert len(store.list_revision_history(integration_id)) == 1


def test_concurrent_same_revision_reuses_winner_with_nonsemantic_metadata(postgres_dsn: str) -> None:
    store, integration_id = _seed(postgres_dsn)
    draft = store.create_draft(integration_id, _descriptor(), {}, None)
    first = OnlyIntegrationRevision.from_draft(draft, 1, "a" * 64, (), NOW)
    second = replace(first, revision_sequence=99, created_at=datetime(2026, 9, 21, tzinfo=UTC))
    barrier = Barrier(2)

    class RacingStore(OnlyPostgresIntegrationStore):
        @classmethod
        def _load_revision(cls, connection, revision_fingerprint):  # type: ignore[no-untyped-def]
            revision = super()._load_revision(connection, revision_fingerprint)
            if revision is None:
                barrier.wait()
            return revision

    def insert(revision: OnlyIntegrationRevision) -> OnlyIntegrationPutDisposition:
        return RacingStore(postgres_dsn, now=lambda: NOW).insert_revision(revision, ())

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(insert, (first, second)))

    assert sorted(outcome.value for outcome in outcomes) == ["CREATED", "REUSED"]
    assert len(store.list_revision_history(integration_id)) == 1


def test_revision_binding_constraint_failure_rolls_back_revision(postgres_dsn: str) -> None:
    store, integration_id = _seed(postgres_dsn)
    draft = store.create_draft(integration_id, _descriptor(), {}, None)
    credential = OnlyPostgresCredentialAuthority(postgres_dsn, b"k" * MASTER_KEY_BYTES).create(
        "INTEGRATION_SECRET", integration_id.value, "api_key", "secret"
    )
    binding = OnlyIntegrationSecretBinding("api_key", credential.credential_id, 1)
    revision = OnlyIntegrationRevision.from_draft(draft, 1, "a" * 64, (binding,), NOW)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_revision_binding() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'INJECTED_REVISION_BINDING_FAILURE'; END $$"""
        )
        connection.execute(
            "CREATE TRIGGER reject_revision_binding_trigger BEFORE INSERT ON integration_revision_secret_binding "
            "FOR EACH ROW EXECUTE FUNCTION reject_revision_binding()"
        )

    with pytest.raises(OnlyIntegrationError):
        store.insert_revision(revision, (binding,))

    with pytest.raises(OnlyIntegrationError) as missing:
        store.load_revision(revision.revision_fingerprint)
    assert missing.value.code == "INTEGRATION_REVISION_NOT_FOUND"


def test_current_revision_must_belong_to_same_integration(postgres_dsn: str) -> None:
    store, integration_id = _seed(postgres_dsn)
    draft = store.create_draft(integration_id, _descriptor(), {}, None)
    revision = OnlyIntegrationRevision.from_draft(draft, 1, "a" * 64, (), NOW)
    store.insert_revision(revision, ())
    other_id = OnlyIntegrationId("672e3601-506f-45ea-ad7e-452e36f548ea")
    store.create_integration(other_id, _descriptor().type_id, "Secondary Binance")

    with pytest.raises(OnlyIntegrationError) as mismatch:
        store.set_current_revision(other_id, revision.revision_fingerprint)
    assert mismatch.value.code == "INTEGRATION_PERSISTENCE_CONFLICT"


def test_schema_has_no_persisted_integration_type_authority(postgres_dsn: str) -> None:
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute("SELECT to_regclass('public.integration_type')").fetchone()

    assert row == (None,)


def test_credential_identity_migration_fails_closed_without_rewriting_development_secret(
    postgres_dsn: str, tmp_path: Path
) -> None:
    migration_root = tmp_path / "migrations"
    migration_root.mkdir()
    for source in sorted(DEFAULT_MIGRATION_ROOT.glob("*.sql")):
        if source.stem > "0026_product_credential_authority":
            break
        (migration_root / source.name).write_bytes(source.read_bytes())
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=migration_root).migrate()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO product_credential "
            "(credential_id, credential_kind, provider_id, ciphertext, key_version, created_at, updated_at) "
            "VALUES (%s, 'BROKER', 'binance', %s, 1, %s, %s)",
            ("ba13b6b1-af9a-450f-833d-48f5002297dc", b"x" * 29, NOW, NOW),
        )

    with pytest.raises(OnlyPostgresMigrationIntegrityError):
        OnlyPostgresMigrationAuthority(postgres_dsn).migrate()

    with psycopg.connect(postgres_dsn) as connection:
        columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'product_credential'"
            ).fetchall()
        }
        count = connection.execute("SELECT count(*) FROM product_credential").fetchone()
    assert "provider_id" in columns and "subject_id" not in columns
    assert count == (1,)
