"""Atomic PostgreSQL adapter for Integration Product commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import cast

import psycopg
from psycopg.rows import dict_row

from onlyalpha.application.integration_application import (
    OnlyIntegrationCommandResult,
    OnlyIntegrationConfigurationResolver,
)
from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationDraft,
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.application.product_command_authority import (
    OnlyProductCommandAdmissionCorruptError,
    OnlyProductCommandConflictError,
    OnlyProductCommandReceiptCorruptError,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.core.clock import only_system_utc_now
from onlyalpha.plugin.integration import OnlyIntegrationTypeDescriptorV1

from .config import OnlyPostgresOperationalConnectionOptions
from .credentials import OnlyCredentialError, OnlyPostgresCredentialAuthority
from .integration_store import OnlyPostgresIntegrationStore
from .product_command_authority import OnlyPostgresProductCommandAuthority

type _Connection = psycopg.Connection[dict[str, object]]
type _Operation = Callable[[_Connection, OnlyPostgresIntegrationStore], str]


class OnlyPostgresIntegrationProductStore(OnlyPostgresIntegrationStore):
    """Commit Product admission, one Integration effect, and Receipt together."""

    def __init__(
        self,
        dsn: str,
        master_key: bytes,
        *,
        options: OnlyPostgresOperationalConnectionOptions | None = None,
        now: Callable[[], datetime] = only_system_utc_now,
    ) -> None:
        super().__init__(dsn, options=options, now=now)
        self._product_dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)
        self._master_key = bytes(master_key)
        self._product_now = now
        self._resolver = OnlyIntegrationConfigurationResolver()

    def replay_command(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        outcome_kind: OnlyProductCommandOutcomeKind,
    ) -> OnlyIntegrationCommandResult | None:
        try:
            with psycopg.connect(self._product_dsn, row_factory=dict_row) as connection:
                authority = OnlyPostgresProductCommandAuthority
                authority.lock_command(connection, admission.command_id)
                existing_admission = authority.load_admission_in_transaction(connection, admission.command_id)
                existing = authority.load_verified_receipt_in_transaction(connection, admission.command_id)
                if existing_admission is None:
                    return None
                if existing_admission != admission:
                    raise OnlyProductCommandConflictError(admission.command_id.value)
                if existing is None:
                    raise OnlyProductCommandReceiptCorruptError(admission.command_id.value)
                store = OnlyPostgresIntegrationStore(
                    self._product_dsn,
                    now=self._product_now,
                    _connection=connection,
                )
                self._verify_receipt(existing, admission, integration_id, outcome_kind, store)
                return OnlyIntegrationCommandResult(existing, replayed=True)
        except (
            OnlyProductCommandAdmissionCorruptError,
            OnlyProductCommandConflictError,
            OnlyProductCommandReceiptCorruptError,
        ):
            raise
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT") from exc

    def create_integration_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        display_name: str,
    ) -> OnlyIntegrationCommandResult:
        def operation(connection: _Connection, store: OnlyPostgresIntegrationStore) -> str:
            del connection
            store.create_integration(integration_id, descriptor.type_id, display_name)
            store.create_draft(integration_id, descriptor, {}, None)
            return integration_id.value

        return self._execute(admission, integration_id, OnlyProductCommandOutcomeKind.INTEGRATION, operation)

    def update_draft_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        public_configuration: Mapping[str, object],
        probe_configuration: Mapping[str, object] | None,
    ) -> OnlyIntegrationCommandResult:
        def operation(connection: _Connection, store: OnlyPostgresIntegrationStore) -> str:
            integration, draft = self._locked_state(connection, store, integration_id)
            self._require_authoring(integration, draft, descriptor, expected_draft_version)
            public, probe = self._resolver.validate_draft(descriptor, public_configuration, probe_configuration)
            store.update_draft(
                integration_id,
                expected_draft_version,
                descriptor,
                public,
                probe,
                base_revision_fingerprint=draft.base_revision_fingerprint,
            )
            return integration_id.value

        return self._execute(admission, integration_id, OnlyProductCommandOutcomeKind.INTEGRATION, operation)

    def set_secret_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        field_id: str,
        plaintext_secret: str,
    ) -> OnlyIntegrationCommandResult:
        def operation(connection: _Connection, store: OnlyPostgresIntegrationStore) -> str:
            integration, draft = self._locked_state(connection, store, integration_id)
            self._require_authoring(integration, draft, descriptor, expected_draft_version)
            self._require_secret_field(descriptor, field_id)
            metadata = OnlyPostgresCredentialAuthority(
                self._product_dsn, self._master_key, now=self._product_now
            ).set_slot_in_transaction(
                connection,
                "INTEGRATION_SECRET",
                integration_id.value,
                field_id,
                plaintext_secret,
            )
            bindings = tuple(
                item for item in store.load_draft_secret_bindings(integration_id) if item.field_id != field_id
            ) + (OnlyIntegrationSecretBinding(field_id, metadata.credential_id, metadata.generation),)
            store.replace_draft_secret_bindings(integration_id, expected_draft_version, bindings)
            return integration_id.value

        return self._execute(admission, integration_id, OnlyProductCommandOutcomeKind.INTEGRATION, operation)

    def clear_secret_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        field_id: str,
    ) -> OnlyIntegrationCommandResult:
        def operation(connection: _Connection, store: OnlyPostgresIntegrationStore) -> str:
            integration, draft = self._locked_state(connection, store, integration_id)
            self._require_authoring(integration, draft, descriptor, expected_draft_version)
            self._require_secret_field(descriptor, field_id)
            bindings = tuple(
                item for item in store.load_draft_secret_bindings(integration_id) if item.field_id != field_id
            )
            store.replace_draft_secret_bindings(integration_id, expected_draft_version, bindings)
            return integration_id.value

        return self._execute(admission, integration_id, OnlyProductCommandOutcomeKind.INTEGRATION, operation)

    def reset_draft_contract_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
    ) -> OnlyIntegrationCommandResult:
        def operation(connection: _Connection, store: OnlyPostgresIntegrationStore) -> str:
            integration, draft = self._locked_state(connection, store, integration_id)
            self._require_mutable(integration)
            self._require_version(draft, expected_draft_version)
            if integration.type_id != descriptor.type_id.value:
                raise OnlyIntegrationError("INTEGRATION_TYPE_CHANGED")
            store.replace_draft_state(
                integration_id,
                expected_draft_version,
                descriptor,
                {},
                None,
                (),
                base_revision_fingerprint=integration.current_revision_fingerprint,
            )
            return integration_id.value

        return self._execute(admission, integration_id, OnlyProductCommandOutcomeKind.INTEGRATION, operation)

    def publish_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
    ) -> OnlyIntegrationCommandResult:
        def operation(connection: _Connection, store: OnlyPostgresIntegrationStore) -> str:
            integration, draft = self._locked_state(connection, store, integration_id)
            self._require_authoring(integration, draft, descriptor, expected_draft_version)
            if draft.base_revision_fingerprint != integration.current_revision_fingerprint:
                raise OnlyIntegrationError("INTEGRATION_BASE_REVISION_CONFLICT")
            bindings = store.load_draft_secret_bindings(integration_id)
            resolution = self._resolver.resolve_publication(
                integration_id,
                descriptor,
                draft.public_configuration_document,
                draft.probe_configuration_document,
                bindings,
            )
            sequence_row = connection.execute(
                "SELECT COALESCE(max(revision_sequence), 0) + 1 AS next_sequence FROM integration_revision "
                "WHERE integration_id = %s",
                (integration_id.value,),
            ).fetchone()
            if sequence_row is None:
                raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT")
            sequence = int(cast(int, sequence_row["next_sequence"]))
            revision = resolution.to_revision(sequence, self._product_now())
            store.insert_revision(revision, resolution.secret_bindings)
            store.set_current_revision(integration_id, revision.revision_fingerprint)
            store.replace_draft_state(
                integration_id,
                expected_draft_version,
                descriptor,
                resolution.public_configuration,
                resolution.probe_configuration,
                resolution.secret_bindings,
                base_revision_fingerprint=revision.revision_fingerprint,
            )
            return revision.revision_fingerprint

        return self._execute(admission, integration_id, OnlyProductCommandOutcomeKind.INTEGRATION_REVISION, operation)

    def set_lifecycle_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_lifecycle_state: OnlyIntegrationLifecycleState,
        lifecycle_state: OnlyIntegrationLifecycleState,
    ) -> OnlyIntegrationCommandResult:
        def operation(connection: _Connection, store: OnlyPostgresIntegrationStore) -> str:
            del store
            row = connection.execute(
                "SELECT lifecycle_state FROM integration WHERE integration_id = %s FOR UPDATE",
                (integration_id.value,),
            ).fetchone()
            if row is None:
                raise OnlyIntegrationError("INTEGRATION_NOT_FOUND")
            current = OnlyIntegrationLifecycleState(str(row["lifecycle_state"]))
            allowed = {
                (OnlyIntegrationLifecycleState.ACTIVE, OnlyIntegrationLifecycleState.DISABLED),
                (OnlyIntegrationLifecycleState.DISABLED, OnlyIntegrationLifecycleState.ACTIVE),
                (OnlyIntegrationLifecycleState.ACTIVE, OnlyIntegrationLifecycleState.ARCHIVED),
                (OnlyIntegrationLifecycleState.DISABLED, OnlyIntegrationLifecycleState.ARCHIVED),
            }
            if current is not expected_lifecycle_state or (current, lifecycle_state) not in allowed:
                raise OnlyIntegrationError("INTEGRATION_LIFECYCLE_CONFLICT")
            updated = connection.execute(
                "UPDATE integration SET lifecycle_state = %s, updated_at = %s "
                "WHERE integration_id = %s AND lifecycle_state = %s RETURNING integration_id",
                (lifecycle_state.value, self._product_now(), integration_id.value, current.value),
            ).fetchone()
            if updated is None:
                raise OnlyIntegrationError("INTEGRATION_LIFECYCLE_CONFLICT")
            return integration_id.value

        return self._execute(admission, integration_id, OnlyProductCommandOutcomeKind.INTEGRATION, operation)

    def _execute(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        outcome_kind: OnlyProductCommandOutcomeKind,
        operation: _Operation,
    ) -> OnlyIntegrationCommandResult:
        try:
            with psycopg.connect(self._product_dsn, row_factory=dict_row) as connection:
                authority = OnlyPostgresProductCommandAuthority
                authority.insert_or_verify_admission(connection, admission)
                existing = authority.load_verified_receipt_in_transaction(connection, admission.command_id)
                store = OnlyPostgresIntegrationStore(
                    self._product_dsn,
                    now=self._product_now,
                    _connection=connection,
                )
                if existing is not None:
                    self._verify_receipt(existing, admission, integration_id, outcome_kind, store)
                    return OnlyIntegrationCommandResult(existing, replayed=True)
                outcome_id = operation(connection, store)
                receipt = OnlyProductCommandReceipt(
                    admission.command_id,
                    admission.command_kind,
                    admission.command_fingerprint,
                    OnlyProductCommandOutcomeRef(outcome_kind, outcome_id),
                    self._product_now(),
                )
                self._verify_receipt(receipt, admission, integration_id, outcome_kind, store)
                authority.insert_verified_receipt(connection, receipt)
                return OnlyIntegrationCommandResult(receipt, replayed=False)
        except (
            OnlyIntegrationError,
            OnlyProductCommandAdmissionCorruptError,
            OnlyProductCommandConflictError,
            OnlyProductCommandReceiptCorruptError,
        ):
            raise
        except OnlyCredentialError as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", exc.code) from exc
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT") from exc

    @staticmethod
    def _verify_receipt(
        receipt: OnlyProductCommandReceipt,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        outcome_kind: OnlyProductCommandOutcomeKind,
        store: OnlyPostgresIntegrationStore,
    ) -> None:
        if (
            receipt.command_kind is not admission.command_kind
            or receipt.command_fingerprint != admission.command_fingerprint
            or receipt.outcome_ref.kind is not outcome_kind
            or (
                outcome_kind is OnlyProductCommandOutcomeKind.INTEGRATION
                and receipt.outcome_ref.outcome_id != integration_id.value
            )
        ):
            raise OnlyProductCommandReceiptCorruptError(admission.command_id.value)
        try:
            if outcome_kind is OnlyProductCommandOutcomeKind.INTEGRATION:
                store.load_integration(integration_id)
            elif store.load_revision(receipt.outcome_ref.outcome_id).integration_id != integration_id:
                raise OnlyProductCommandReceiptCorruptError(admission.command_id.value)
        except OnlyIntegrationError as exc:
            raise OnlyProductCommandReceiptCorruptError(admission.command_id.value) from exc

    @staticmethod
    def _locked_state(
        connection: _Connection,
        store: OnlyPostgresIntegrationStore,
        integration_id: OnlyIntegrationId,
    ) -> tuple[OnlyIntegration, OnlyIntegrationDraft]:
        row = connection.execute(
            "SELECT integration.integration_id FROM integration "
            "JOIN integration_draft USING (integration_id) "
            "WHERE integration.integration_id = %s FOR UPDATE OF integration, integration_draft",
            (integration_id.value,),
        ).fetchone()
        if row is None:
            store.load_integration(integration_id)
            raise OnlyIntegrationError("INTEGRATION_DRAFT_NOT_FOUND")
        return store.load_integration(integration_id), store.load_draft(integration_id)

    @staticmethod
    def _require_mutable(integration: OnlyIntegration) -> None:
        if integration.lifecycle_state is OnlyIntegrationLifecycleState.ARCHIVED:
            raise OnlyIntegrationError("INTEGRATION_ARCHIVED")

    @staticmethod
    def _require_version(draft: OnlyIntegrationDraft, expected_draft_version: int) -> None:
        if draft.draft_version != expected_draft_version:
            raise OnlyIntegrationError("INTEGRATION_DRAFT_VERSION_CONFLICT")

    @classmethod
    def _require_authoring(
        cls,
        integration: OnlyIntegration,
        draft: OnlyIntegrationDraft,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        expected_draft_version: int,
    ) -> None:
        cls._require_mutable(integration)
        cls._require_version(draft, expected_draft_version)
        if integration.type_id != descriptor.type_id.value:
            raise OnlyIntegrationError("INTEGRATION_TYPE_CHANGED")
        if draft.type_descriptor_fingerprint != descriptor.fingerprint:
            raise OnlyIntegrationError("INTEGRATION_TYPE_CHANGED")

    @staticmethod
    def _require_secret_field(descriptor: OnlyIntegrationTypeDescriptorV1, field_id: str) -> None:
        contract = next(
            (item for item in descriptor.configuration_contract.fields if item.field_id == field_id),
            None,
        )
        if contract is None or not contract.secret:
            raise OnlyIntegrationError("INTEGRATION_SECRET_FIELD_INVALID")


__all__ = ["OnlyPostgresIntegrationProductStore"]
