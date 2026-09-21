from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from onlyalpha.application.integration_application import (
    OnlyClearIntegrationSecret,
    OnlyCreateIntegration,
    OnlyIntegrationCommandService,
    OnlyIntegrationQueryService,
    OnlyPublishIntegrationRevision,
    OnlyResetIntegrationDraftContract,
    OnlySetIntegrationLifecycle,
    OnlySetIntegrationSecret,
    OnlyUpdateIntegrationDraft,
)
from onlyalpha.application.integration_configuration import (
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationSecretBinding,
    only_integration_draft_fingerprint,
)
from onlyalpha.application.product_command_authority import (
    OnlyProductCommandConflictError,
    OnlyProductCommandReceiptCorruptError,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.persistence.postgres.credentials import MASTER_KEY_BYTES, OnlyPostgresCredentialAuthority
from onlyalpha.persistence.postgres.integration_product_store import OnlyPostgresIntegrationProductStore
from onlyalpha.persistence.postgres.migration import DEFAULT_MIGRATION_ROOT, OnlyPostgresMigrationAuthority
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
NOW = datetime(2026, 9, 21, tzinfo=UTC)
MASTER_KEY = b"k" * MASTER_KEY_BYTES
INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")


def _command(number: int) -> OnlyProductCommandId:
    return OnlyProductCommandId(f"00000000-0000-4000-8000-{number:012d}")


def _descriptor(*, version: str = "1.0.0") -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId("binance.spot.market_data"),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Binance Spot",
        description="Binance Spot market data",
        provider_id="binance",
        implementation_id="binance",
        implementation_version=version,
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
                    "name",
                    OnlyIntegrationValueKind.STRING,
                    required=True,
                    display_name="Name",
                ),
                OnlyIntegrationConfigurationFieldV1(
                    "timeout_seconds",
                    OnlyIntegrationValueKind.DURATION,
                    required=False,
                    default=10.0,
                    minimum=0.1,
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


@dataclass
class _Catalog:
    descriptor: OnlyIntegrationTypeDescriptorV1

    def require(self, type_id: str) -> OnlyIntegrationTypeDescriptorV1:
        if type_id != self.descriptor.type_id.value:
            raise LookupError(type_id)
        return self.descriptor


class _CatalogUnavailable:
    def require(self, type_id: str) -> OnlyIntegrationTypeDescriptorV1:
        raise LookupError(type_id)


def _service(postgres_dsn: str, descriptor: OnlyIntegrationTypeDescriptorV1 | None = None):  # type: ignore[no-untyped-def]
    store = OnlyPostgresIntegrationProductStore(postgres_dsn, MASTER_KEY, now=lambda: NOW)
    return OnlyIntegrationCommandService(_Catalog(descriptor or _descriptor()), store, MASTER_KEY), store


def _create(service: OnlyIntegrationCommandService, command_id: int = 1):  # type: ignore[no-untyped-def]
    return service.create_integration(
        OnlyCreateIntegration(
            _command(command_id),
            INTEGRATION_ID,
            _descriptor().type_id.value,
            "Primary Binance",
        )
    )


def test_create_is_atomic_replayable_and_restart_safe(postgres_dsn: str) -> None:
    service, store = _service(postgres_dsn)

    first = _create(service)
    replay = _create(service)
    restarted, _ = _service(postgres_dsn)
    replay_after_restart = _create(restarted)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay_after_restart.replayed is True
    assert store.load_draft(INTEGRATION_ID).draft_version == 1
    assert store.load_draft(INTEGRATION_ID).public_configuration_document == {}
    with pytest.raises(OnlyProductCommandConflictError):
        service.create_integration(
            OnlyCreateIntegration(_command(1), INTEGRATION_ID, _descriptor().type_id.value, "Changed")
        )


def test_draft_update_is_cas_and_contract_change_requires_explicit_reset(postgres_dsn: str) -> None:
    service, store = _service(postgres_dsn)
    _create(service)

    updated = service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"timeout_seconds": 2.0}, None)
    )
    replay = service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"timeout_seconds": 2}, None)
    )

    assert updated.replayed is False and replay.replayed is True
    assert store.load_draft(INTEGRATION_ID).public_configuration_document == {"timeout_seconds": 2}
    with pytest.raises(OnlyProductCommandConflictError):
        service.update_integration_draft(
            OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"timeout_seconds": 3}, None)
        )
    with pytest.raises(OnlyIntegrationError) as stale:
        service.update_integration_draft(
            OnlyUpdateIntegrationDraft(_command(3), INTEGRATION_ID, 1, {"timeout_seconds": 3}, None)
        )
    assert stale.value.code == "INTEGRATION_DRAFT_VERSION_CONFLICT"

    changed_service, _ = _service(postgres_dsn, _descriptor(version="2.0.0"))
    with pytest.raises(OnlyIntegrationError) as changed:
        changed_service.update_integration_draft(
            OnlyUpdateIntegrationDraft(_command(4), INTEGRATION_ID, 2, {"timeout_seconds": 3}, None)
        )
    assert changed.value.code == "INTEGRATION_TYPE_CHANGED"

    reset_command = OnlyResetIntegrationDraftContract(_command(5), INTEGRATION_ID, 2)
    changed_service.reset_integration_draft_contract(reset_command)
    assert changed_service.reset_integration_draft_contract(reset_command).replayed is True
    with pytest.raises(OnlyProductCommandConflictError):
        changed_service.reset_integration_draft_contract(
            OnlyResetIntegrationDraftContract(_command(5), INTEGRATION_ID, 3)
        )
    reset = store.load_draft(INTEGRATION_ID)
    assert reset.type_descriptor_fingerprint == _descriptor(version="2.0.0").fingerprint
    assert reset.public_configuration_document == {}
    assert store.load_draft_secret_bindings(INTEGRATION_ID) == ()


def test_secret_set_replays_without_rotation_and_clear_keeps_credential_history(postgres_dsn: str) -> None:
    service, store = _service(postgres_dsn)
    _create(service)
    command = OnlySetIntegrationSecret(_command(2), INTEGRATION_ID, 1, "api_key", "secret")

    first = service.set_integration_secret(command)
    replay = service.set_integration_secret(command)

    assert first.replayed is False and replay.replayed is True
    binding = store.load_draft_secret_bindings(INTEGRATION_ID)[0]
    assert binding.credential_generation == 1
    assert store.load_draft(INTEGRATION_ID).draft_version == 2
    with pytest.raises(OnlyProductCommandConflictError):
        service.set_integration_secret(OnlySetIntegrationSecret(_command(2), INTEGRATION_ID, 1, "api_key", "changed"))

    clear_command = OnlyClearIntegrationSecret(_command(3), INTEGRATION_ID, 2, "api_key")
    service.clear_integration_secret(clear_command)
    assert service.clear_integration_secret(clear_command).replayed is True
    with pytest.raises(OnlyProductCommandConflictError):
        service.clear_integration_secret(OnlyClearIntegrationSecret(_command(3), INTEGRATION_ID, 3, "api_key"))
    assert store.load_draft_secret_bindings(INTEGRATION_ID) == ()
    assert len(OnlyPostgresCredentialAuthority(postgres_dsn, MASTER_KEY).list_metadata()) == 1
    with psycopg.connect(postgres_dsn) as connection:
        command_text = connection.execute(
            "SELECT concat_ws('|', command_kind, command_fingerprint) "
            "FROM product_command_admission WHERE command_id = %s",
            (_command(2).value,),
        ).fetchone()
        receipt_text = connection.execute(
            "SELECT concat_ws('|', command_kind, command_fingerprint, outcome_kind, outcome_id) "
            "FROM product_command_receipt WHERE command_id = %s",
            (_command(2).value,),
        ).fetchone()
    assert "secret" not in str(command_text)
    assert "secret" not in str(receipt_text)


def test_publish_is_atomic_rebases_draft_and_converges_on_exact_revision(postgres_dsn: str) -> None:
    service, store = _service(postgres_dsn)
    _create(service)
    service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"name": "primary"}, None)
    )
    service.set_integration_secret(OnlySetIntegrationSecret(_command(3), INTEGRATION_ID, 2, "api_key", "secret"))

    first = service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(4), INTEGRATION_ID, 3))
    replay = service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(4), INTEGRATION_ID, 3))
    with pytest.raises(OnlyProductCommandConflictError):
        service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(4), INTEGRATION_ID, 4))
    revision = store.load_revision(first.receipt.outcome_ref.outcome_id)
    rebased = store.load_draft(INTEGRATION_ID)

    assert first.replayed is False and replay.replayed is True
    assert revision.configuration_document == {"name": "primary", "timeout_seconds": 10}
    assert revision.probe_configuration_document == {"instrument": "BTCUSDT"}
    assert store.load_integration(INTEGRATION_ID).current_revision_fingerprint == revision.revision_fingerprint
    assert rebased.base_revision_fingerprint == revision.revision_fingerprint
    assert rebased.draft_version == 4

    no_op = service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(5), INTEGRATION_ID, 4))
    assert no_op.receipt.outcome_ref.outcome_id == revision.revision_fingerprint
    assert len(store.list_revision_history(INTEGRATION_ID)) == 1


def test_publish_rejects_incomplete_and_stale_secret_generation(postgres_dsn: str) -> None:
    service, store = _service(postgres_dsn)
    _create(service)
    with pytest.raises(OnlyIntegrationError) as incomplete:
        service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(2), INTEGRATION_ID, 1))
    assert incomplete.value.code == "INTEGRATION_CONFIGURATION_INCOMPLETE"

    service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(3), INTEGRATION_ID, 1, {"name": "primary"}, None)
    )
    service.set_integration_secret(OnlySetIntegrationSecret(_command(4), INTEGRATION_ID, 2, "api_key", "old"))
    binding = store.load_draft_secret_bindings(INTEGRATION_ID)[0]
    OnlyPostgresCredentialAuthority(postgres_dsn, MASTER_KEY).rotate(binding.credential_id, 1, "new")

    with pytest.raises(OnlyIntegrationError) as stale:
        service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(5), INTEGRATION_ID, 3))
    assert stale.value.code == "INTEGRATION_SECRET_BINDING_INVALID"
    assert store.load_integration(INTEGRATION_ID).current_revision_fingerprint is None


def test_publish_rejects_credential_owned_by_another_integration(postgres_dsn: str) -> None:
    service, store = _service(postgres_dsn)
    _create(service)
    service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"name": "primary"}, None)
    )
    service.set_integration_secret(OnlySetIntegrationSecret(_command(3), INTEGRATION_ID, 2, "api_key", "secret"))
    other_id = OnlyIntegrationId("672e3601-506f-45ea-ad7e-452e36f548ea")
    other = OnlyPostgresCredentialAuthority(postgres_dsn, MASTER_KEY).create(
        "INTEGRATION_SECRET", other_id.value, "api_key", "other-secret"
    )
    draft = store.load_draft(INTEGRATION_ID)
    wrong_binding = OnlyIntegrationSecretBinding("api_key", other.credential_id, other.generation)
    fingerprint = only_integration_draft_fingerprint(
        INTEGRATION_ID,
        draft.base_revision_fingerprint,
        draft.type_descriptor_fingerprint,
        draft.type_descriptor_document,
        draft.public_configuration_document,
        draft.probe_configuration_document,
        (wrong_binding,),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE integration_draft_secret_binding SET credential_id = %s, credential_generation = %s "
            "WHERE integration_id = %s",
            (wrong_binding.credential_id, wrong_binding.credential_generation, INTEGRATION_ID.value),
        )
        connection.execute(
            "UPDATE integration_draft SET draft_fingerprint = %s WHERE integration_id = %s",
            (fingerprint, INTEGRATION_ID.value),
        )

    with pytest.raises(OnlyIntegrationError) as wrong_subject:
        service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(4), INTEGRATION_ID, 3))

    assert wrong_subject.value.code == "INTEGRATION_SECRET_BINDING_INVALID"
    assert store.load_integration(INTEGRATION_ID).current_revision_fingerprint is None


def test_publish_rejects_stale_base_and_unavailable_or_changed_type_without_state_change(
    postgres_dsn: str,
) -> None:
    service, store = _service(postgres_dsn)
    _create(service)
    service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"name": "primary"}, None)
    )
    service.set_integration_secret(OnlySetIntegrationSecret(_command(3), INTEGRATION_ID, 2, "api_key", "secret"))
    first = service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(4), INTEGRATION_ID, 3))
    service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(5), INTEGRATION_ID, 4, {"name": "changed"}, None)
    )
    draft = store.load_draft(INTEGRATION_ID)
    stale_fingerprint = only_integration_draft_fingerprint(
        INTEGRATION_ID,
        None,
        draft.type_descriptor_fingerprint,
        draft.type_descriptor_document,
        draft.public_configuration_document,
        draft.probe_configuration_document,
        store.load_draft_secret_bindings(INTEGRATION_ID),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE integration_draft SET base_revision_fingerprint = NULL, draft_fingerprint = %s "
            "WHERE integration_id = %s",
            (stale_fingerprint, INTEGRATION_ID.value),
        )

    with pytest.raises(OnlyIntegrationError) as stale_base:
        service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(6), INTEGRATION_ID, 5))
    assert stale_base.value.code == "INTEGRATION_BASE_REVISION_CONFLICT"

    changed_service, _ = _service(postgres_dsn, _descriptor(version="2.0.0"))
    with pytest.raises(OnlyIntegrationError) as changed:
        changed_service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(7), INTEGRATION_ID, 5))
    assert changed.value.code == "INTEGRATION_TYPE_CHANGED"

    unavailable = OnlyIntegrationCommandService(_CatalogUnavailable(), store, MASTER_KEY)
    with pytest.raises(OnlyIntegrationError) as missing:
        unavailable.publish_integration_revision(OnlyPublishIntegrationRevision(_command(8), INTEGRATION_ID, 5))
    assert missing.value.code == "INTEGRATION_TYPE_UNAVAILABLE"
    assert store.load_integration(INTEGRATION_ID).current_revision_fingerprint == first.receipt.outcome_ref.outcome_id
    assert len(store.list_revision_history(INTEGRATION_ID)) == 1


@pytest.mark.parametrize(
    ("table", "event"),
    (
        ("integration_revision", "INSERT"),
        ("integration_revision_secret_binding", "INSERT"),
        ("integration", "UPDATE"),
        ("integration_draft", "UPDATE"),
        ("product_command_receipt", "INSERT"),
    ),
)
def test_publish_failure_at_each_durable_boundary_rolls_back_every_effect(
    postgres_dsn: str,
    table: str,
    event: str,
) -> None:
    service, store = _service(postgres_dsn)
    _create(service)
    service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"name": "primary"}, None)
    )
    service.set_integration_secret(OnlySetIntegrationSecret(_command(3), INTEGRATION_ID, 2, "api_key", "secret"))
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_publish_boundary() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'INJECTED_PUBLISH_FAILURE'; END $$"""
        )
        connection.execute(
            f"CREATE TRIGGER reject_publish_boundary BEFORE {event} ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_publish_boundary()"
        )

    with pytest.raises(OnlyIntegrationError) as failed:
        service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(4), INTEGRATION_ID, 3))

    assert failed.value.code == "INTEGRATION_PERSISTENCE_CONFLICT"
    integration = store.load_integration(INTEGRATION_ID)
    draft = store.load_draft(INTEGRATION_ID)
    assert integration.current_revision_fingerprint is None
    assert draft.draft_version == 3 and draft.base_revision_fingerprint is None
    assert store.list_revision_history(INTEGRATION_ID) == ()
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM product_command_admission WHERE command_id = %s",
            (_command(4).value,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM product_command_receipt WHERE command_id = %s",
            (_command(4).value,),
        ).fetchone() == (0,)


def test_secret_mutation_rolls_back_credential_draft_admission_and_receipt(postgres_dsn: str) -> None:
    service, store = _service(postgres_dsn)
    _create(service)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_secret_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.command_kind = 'SET_INTEGRATION_SECRET' THEN
                    RAISE EXCEPTION 'INJECTED_SECRET_RECEIPT_FAILURE';
                END IF;
                RETURN NEW;
            END $$"""
        )
        connection.execute(
            "CREATE TRIGGER reject_secret_receipt_trigger BEFORE INSERT ON product_command_receipt "
            "FOR EACH ROW EXECUTE FUNCTION reject_secret_receipt()"
        )

    with pytest.raises(OnlyIntegrationError) as failed:
        service.set_integration_secret(OnlySetIntegrationSecret(_command(2), INTEGRATION_ID, 1, "api_key", "secret"))
    assert failed.value.code == "INTEGRATION_PERSISTENCE_CONFLICT"
    assert store.load_draft(INTEGRATION_ID).draft_version == 1
    assert store.load_draft_secret_bindings(INTEGRATION_ID) == ()
    assert OnlyPostgresCredentialAuthority(postgres_dsn, MASTER_KEY).list_metadata() == ()
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM product_command_admission WHERE command_id = %s", (_command(2).value,)
        ).fetchone() == (0,)


def test_lifecycle_transitions_are_atomic_archived_is_terminal_and_queries_remain_available(postgres_dsn: str) -> None:
    service, store = _service(postgres_dsn)
    _create(service)
    service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(20), INTEGRATION_ID, 1, {"name": "primary"}, None)
    )
    service.set_integration_secret(OnlySetIntegrationSecret(_command(21), INTEGRATION_ID, 2, "api_key", "secret"))
    published = service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(22), INTEGRATION_ID, 3))
    disable_command = OnlySetIntegrationLifecycle(
        _command(2),
        INTEGRATION_ID,
        OnlyIntegrationLifecycleState.ACTIVE,
        OnlyIntegrationLifecycleState.DISABLED,
    )
    service.set_integration_lifecycle(disable_command)
    assert service.set_integration_lifecycle(disable_command).replayed is True
    with pytest.raises(OnlyProductCommandConflictError):
        service.set_integration_lifecycle(
            OnlySetIntegrationLifecycle(
                _command(2),
                INTEGRATION_ID,
                OnlyIntegrationLifecycleState.DISABLED,
                OnlyIntegrationLifecycleState.ARCHIVED,
            )
        )
    service.set_integration_lifecycle(
        OnlySetIntegrationLifecycle(
            _command(3),
            INTEGRATION_ID,
            OnlyIntegrationLifecycleState.DISABLED,
            OnlyIntegrationLifecycleState.ACTIVE,
        )
    )
    service.set_integration_lifecycle(
        OnlySetIntegrationLifecycle(
            _command(4),
            INTEGRATION_ID,
            OnlyIntegrationLifecycleState.ACTIVE,
            OnlyIntegrationLifecycleState.ARCHIVED,
        )
    )

    with pytest.raises(OnlyIntegrationError) as terminal:
        service.set_integration_lifecycle(
            OnlySetIntegrationLifecycle(
                _command(5),
                INTEGRATION_ID,
                OnlyIntegrationLifecycleState.ARCHIVED,
                OnlyIntegrationLifecycleState.ACTIVE,
            )
        )
    assert terminal.value.code == "INTEGRATION_LIFECYCLE_CONFLICT"
    with pytest.raises(OnlyIntegrationError) as archived:
        service.update_integration_draft(
            OnlyUpdateIntegrationDraft(_command(6), INTEGRATION_ID, 4, {"name": "blocked"}, None)
        )
    assert archived.value.code == "INTEGRATION_ARCHIVED"
    archived_commands = (
        lambda: service.set_integration_secret(
            OnlySetIntegrationSecret(_command(7), INTEGRATION_ID, 4, "api_key", "blocked")
        ),
        lambda: service.clear_integration_secret(OnlyClearIntegrationSecret(_command(8), INTEGRATION_ID, 4, "api_key")),
        lambda: service.reset_integration_draft_contract(
            OnlyResetIntegrationDraftContract(_command(9), INTEGRATION_ID, 4)
        ),
        lambda: service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(10), INTEGRATION_ID, 4)),
    )
    for mutate in archived_commands:
        with pytest.raises(OnlyIntegrationError) as blocked:
            mutate()
        assert blocked.value.code == "INTEGRATION_ARCHIVED"
    query = OnlyIntegrationQueryService(store)
    assert query.get_integration(INTEGRATION_ID).lifecycle_state is OnlyIntegrationLifecycleState.ARCHIVED
    assert query.get_current_revision(INTEGRATION_ID).revision_fingerprint == published.receipt.outcome_ref.outcome_id
    assert (
        query.list_revision_history(INTEGRATION_ID)[0].revision_fingerprint == published.receipt.outcome_ref.outcome_id
    )
    assert query.get_draft_secret_status(INTEGRATION_ID)[0].configured is True


def test_every_accepted_command_replays_before_archive_or_catalog_checks(postgres_dsn: str) -> None:
    service, store = _service(postgres_dsn)
    create = OnlyCreateIntegration(_command(1), INTEGRATION_ID, _descriptor().type_id.value, "Primary Binance")
    update = OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"name": "primary"}, None)
    secret = OnlySetIntegrationSecret(_command(3), INTEGRATION_ID, 2, "api_key", "secret")
    clear = OnlyClearIntegrationSecret(_command(4), INTEGRATION_ID, 3, "api_key")
    reset = OnlyResetIntegrationDraftContract(_command(5), INTEGRATION_ID, 4)
    changed_service, _ = _service(postgres_dsn, _descriptor(version="2.0.0"))
    changed_update = OnlyUpdateIntegrationDraft(_command(6), INTEGRATION_ID, 5, {"name": "1.5"}, None)
    changed_secret = OnlySetIntegrationSecret(_command(7), INTEGRATION_ID, 6, "api_key", "new-secret")
    publish = OnlyPublishIntegrationRevision(_command(8), INTEGRATION_ID, 7)
    archive = OnlySetIntegrationLifecycle(
        _command(9),
        INTEGRATION_ID,
        OnlyIntegrationLifecycleState.ACTIVE,
        OnlyIntegrationLifecycleState.ARCHIVED,
    )

    service.create_integration(create)
    service.update_integration_draft(update)
    service.set_integration_secret(secret)
    service.clear_integration_secret(clear)
    changed_service.reset_integration_draft_contract(reset)
    changed_service.update_integration_draft(changed_update)
    changed_service.set_integration_secret(changed_secret)
    changed_service.publish_integration_revision(publish)
    assert _service(postgres_dsn, _descriptor(version="3.0.0"))[0].reset_integration_draft_contract(reset).replayed
    changed_service.set_integration_lifecycle(archive)

    unavailable = OnlyIntegrationCommandService(_CatalogUnavailable(), store, MASTER_KEY)
    replays = (
        unavailable.create_integration(create),
        unavailable.update_integration_draft(update),
        unavailable.set_integration_secret(secret),
        unavailable.clear_integration_secret(clear),
        unavailable.reset_integration_draft_contract(reset),
        unavailable.update_integration_draft(changed_update),
        unavailable.set_integration_secret(changed_secret),
        unavailable.publish_integration_revision(publish),
        unavailable.set_integration_lifecycle(archive),
    )

    assert all(result.replayed for result in replays)
    with pytest.raises(OnlyProductCommandConflictError):
        unavailable.update_integration_draft(
            OnlyUpdateIntegrationDraft(_command(6), INTEGRATION_ID, 5, {"name": 1.5}, None)
        )


def test_publish_replay_rejects_missing_revision_effect(postgres_dsn: str) -> None:
    service, _ = _service(postgres_dsn)
    _create(service)
    service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"name": "primary"}, None)
    )
    service.set_integration_secret(OnlySetIntegrationSecret(_command(3), INTEGRATION_ID, 2, "api_key", "secret"))
    command = OnlyPublishIntegrationRevision(_command(4), INTEGRATION_ID, 3)
    service.publish_integration_revision(command)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE product_command_receipt SET outcome_id = %s WHERE command_id = %s",
            ("f" * 64, command.command_id.value),
        )

    with pytest.raises(OnlyProductCommandReceiptCorruptError):
        service.publish_integration_revision(command)


def test_publish_replay_rejects_revision_owned_by_another_integration(postgres_dsn: str) -> None:
    service, _ = _service(postgres_dsn)
    _create(service)
    service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"name": "primary"}, None)
    )
    service.set_integration_secret(OnlySetIntegrationSecret(_command(3), INTEGRATION_ID, 2, "api_key", "secret"))
    command = OnlyPublishIntegrationRevision(_command(4), INTEGRATION_ID, 3)
    service.publish_integration_revision(command)

    other_id = OnlyIntegrationId("672e3601-506f-45ea-ad7e-452e36f548ea")
    service.create_integration(
        OnlyCreateIntegration(_command(10), other_id, _descriptor().type_id.value, "Other Binance")
    )
    service.update_integration_draft(OnlyUpdateIntegrationDraft(_command(11), other_id, 1, {"name": "other"}, None))
    service.set_integration_secret(OnlySetIntegrationSecret(_command(12), other_id, 2, "api_key", "other-secret"))
    foreign = service.publish_integration_revision(OnlyPublishIntegrationRevision(_command(13), other_id, 3))
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE product_command_receipt SET outcome_id = %s WHERE command_id = %s",
            (foreign.receipt.outcome_ref.outcome_id, command.command_id.value),
        )

    with pytest.raises(OnlyProductCommandReceiptCorruptError):
        service.publish_integration_revision(command)


def test_concurrent_create_and_publish_have_one_effect_and_one_replay(postgres_dsn: str) -> None:
    def create() -> bool:
        service, _ = _service(postgres_dsn)
        return _create(service).replayed

    with ThreadPoolExecutor(max_workers=2) as executor:
        create_replays = tuple(executor.map(lambda _: create(), range(2)))
    assert sorted(create_replays) == [False, True]

    service, store = _service(postgres_dsn)
    service.update_integration_draft(
        OnlyUpdateIntegrationDraft(_command(2), INTEGRATION_ID, 1, {"name": "primary"}, None)
    )
    service.set_integration_secret(OnlySetIntegrationSecret(_command(3), INTEGRATION_ID, 2, "api_key", "secret"))

    def publish() -> bool:
        concurrent_service, _ = _service(postgres_dsn)
        return concurrent_service.publish_integration_revision(
            OnlyPublishIntegrationRevision(_command(4), INTEGRATION_ID, 3)
        ).replayed

    with ThreadPoolExecutor(max_workers=2) as executor:
        publish_replays = tuple(executor.map(lambda _: publish(), range(2)))
    assert sorted(publish_replays) == [False, True]
    assert len(store.list_revision_history(INTEGRATION_ID)) == 1


def test_integration_command_constraint_migration_preserves_existing_product_commands(
    postgres_dsn: str,
    tmp_path: Path,
) -> None:
    migration_root = tmp_path / "migrations"
    migration_root.mkdir()
    for source in sorted(DEFAULT_MIGRATION_ROOT.glob("*.sql")):
        if source.stem > "0033_integration_configuration_authority":
            break
        (migration_root / source.name).write_bytes(source.read_bytes())
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    authority = OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=migration_root)
    authority.migrate()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO product_command_admission VALUES (%s, 'CREATE_RESEARCH_RUN', %s, 1)",
            (_command(90).value, "a" * 64),
        )
        connection.execute(
            "INSERT INTO product_command_receipt VALUES (%s, 'CREATE_RESEARCH_RUN', %s, 'RESEARCH_RUN', %s, %s, 1)",
            (_command(90).value, "a" * 64, _command(91).value, NOW),
        )
        before = connection.execute("SELECT * FROM product_command_receipt").fetchall()

    source = DEFAULT_MIGRATION_ROOT / "0034_integration_product_command_authority.sql"
    (migration_root / source.name).write_bytes(source.read_bytes())
    assert OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=migration_root).migrate() == (
        "0034_integration_product_command_authority",
    )
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT * FROM product_command_receipt").fetchall() == before
        connection.execute(
            "INSERT INTO product_command_admission VALUES (%s, 'CREATE_INTEGRATION', %s, 1)",
            (_command(92).value, "b" * 64),
        )
        connection.execute(
            "INSERT INTO product_command_receipt VALUES (%s, 'CREATE_INTEGRATION', %s, 'INTEGRATION', %s, %s, 1)",
            (_command(92).value, "b" * 64, INTEGRATION_ID.value, NOW),
        )
