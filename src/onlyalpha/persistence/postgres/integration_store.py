"""PostgreSQL authority for Integration identity, Drafts, and immutable Revisions."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from typing import cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationDraft,
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
    only_integration_draft_fingerprint,
    only_integration_json_document,
)
from onlyalpha.core.clock import only_system_utc_now
from onlyalpha.plugin.integration import OnlyIntegrationTypeDescriptorV1, OnlyIntegrationTypeId

from .config import OnlyPostgresOperationalConnectionOptions


class OnlyIntegrationPutDisposition(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"


class OnlyPostgresIntegrationStore:
    def __init__(
        self,
        dsn: str,
        *,
        options: OnlyPostgresOperationalConnectionOptions | None = None,
        now: Callable[[], datetime] = only_system_utc_now,
        _connection: psycopg.Connection[dict[str, object]] | None = None,
    ) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)
        self._now = now
        self._connection = _connection

    @contextmanager
    def transaction(self) -> Iterator[OnlyPostgresIntegrationStore]:
        if self._connection is not None:
            with self._connection.transaction():
                yield self
            return
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                yield OnlyPostgresIntegrationStore(self._dsn, now=self._now, _connection=connection)
        except OnlyIntegrationError:
            raise
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "transaction failed") from exc

    def create_integration(
        self,
        integration_id: OnlyIntegrationId,
        type_id: OnlyIntegrationTypeId,
        display_name: str,
    ) -> OnlyIntegration:
        now = self._now()
        integration = OnlyIntegration(
            integration_id,
            type_id.value,
            display_name,
            OnlyIntegrationLifecycleState.ACTIVE,
            None,
            now,
            now,
        )
        try:
            with self._connection_scope() as connection:
                connection.execute(
                    "INSERT INTO integration "
                    "(integration_id, type_id, display_name, lifecycle_state, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        integration.integration_id.value,
                        integration.type_id,
                        integration.display_name,
                        integration.lifecycle_state.value,
                        integration.created_at,
                        integration.updated_at,
                    ),
                )
        except psycopg.IntegrityError as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT") from exc
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Integration create failed") from exc
        return integration

    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    "SELECT integration_id::text, type_id, display_name, lifecycle_state, "
                    "current_revision_fingerprint, created_at, updated_at "
                    "FROM integration WHERE integration_id = %s",
                    (integration_id.value,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Integration load failed") from exc
        if row is None:
            raise OnlyIntegrationError("INTEGRATION_NOT_FOUND")
        try:
            return OnlyIntegration(
                OnlyIntegrationId(str(row["integration_id"])),
                str(row["type_id"]),
                str(row["display_name"]),
                OnlyIntegrationLifecycleState(str(row["lifecycle_state"])),
                cast(str | None, row["current_revision_fingerprint"]),
                cast(datetime, row["created_at"]),
                cast(datetime, row["updated_at"]),
            )
        except (TypeError, ValueError, OnlyIntegrationError) as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Integration row is corrupt") from exc

    def create_draft(
        self,
        integration_id: OnlyIntegrationId,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        public_configuration: Mapping[str, object],
        probe_configuration: Mapping[str, object] | None,
        *,
        base_revision_fingerprint: str | None = None,
    ) -> OnlyIntegrationDraft:
        integration = self.load_integration(integration_id)
        if descriptor.type_id.value != integration.type_id:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Integration Type cannot change")
        draft = OnlyIntegrationDraft.create(
            integration_id=integration_id,
            descriptor=descriptor,
            public_configuration=public_configuration,
            probe_configuration=probe_configuration,
            created_at=self._now(),
            base_revision_fingerprint=base_revision_fingerprint,
        )
        try:
            with self._connection_scope() as connection:
                connection.execute(
                    "INSERT INTO integration_draft "
                    "(integration_id, base_revision_fingerprint, type_descriptor_fingerprint, "
                    "type_descriptor_document, public_configuration_document, probe_configuration_document, "
                    "draft_version, draft_fingerprint, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        integration_id.value,
                        draft.base_revision_fingerprint,
                        draft.type_descriptor_fingerprint,
                        Json(only_integration_json_document(draft.type_descriptor_document)),
                        Json(only_integration_json_document(draft.public_configuration_document)),
                        None
                        if draft.probe_configuration_document is None
                        else Json(only_integration_json_document(draft.probe_configuration_document)),
                        draft.draft_version,
                        draft.draft_fingerprint,
                        draft.created_at,
                        draft.updated_at,
                    ),
                )
        except psycopg.IntegrityError as exc:
            raise OnlyIntegrationError(
                "INTEGRATION_PERSISTENCE_CONFLICT", "Draft already exists or base is invalid"
            ) from exc
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Draft create failed") from exc
        return draft

    def update_draft(
        self,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        public_configuration: Mapping[str, object],
        probe_configuration: Mapping[str, object] | None,
        *,
        base_revision_fingerprint: str | None = None,
    ) -> OnlyIntegrationDraft:
        if expected_draft_version < 1:
            raise OnlyIntegrationError("INTEGRATION_DRAFT_VERSION_CONFLICT")
        current = self.load_draft(integration_id)
        integration = self.load_integration(integration_id)
        if descriptor.type_id.value != integration.type_id:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Integration Type cannot change")
        candidate = OnlyIntegrationDraft.create(
            integration_id=integration_id,
            descriptor=descriptor,
            public_configuration=public_configuration,
            probe_configuration=probe_configuration,
            created_at=current.created_at,
            base_revision_fingerprint=base_revision_fingerprint,
        )
        bindings = self.load_draft_secret_bindings(integration_id)
        updated_at = self._now()
        fingerprint = only_integration_draft_fingerprint(
            integration_id,
            candidate.base_revision_fingerprint,
            candidate.type_descriptor_fingerprint,
            candidate.type_descriptor_document,
            candidate.public_configuration_document,
            candidate.probe_configuration_document,
            bindings,
        )
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    "UPDATE integration_draft SET base_revision_fingerprint = %s, "
                    "type_descriptor_fingerprint = %s, type_descriptor_document = %s, "
                    "public_configuration_document = %s, probe_configuration_document = %s, "
                    "draft_version = draft_version + 1, draft_fingerprint = %s, updated_at = %s "
                    "WHERE integration_id = %s AND draft_version = %s RETURNING draft_version",
                    (
                        candidate.base_revision_fingerprint,
                        candidate.type_descriptor_fingerprint,
                        Json(only_integration_json_document(candidate.type_descriptor_document)),
                        Json(only_integration_json_document(candidate.public_configuration_document)),
                        None
                        if candidate.probe_configuration_document is None
                        else Json(only_integration_json_document(candidate.probe_configuration_document)),
                        fingerprint,
                        updated_at,
                        integration_id.value,
                        expected_draft_version,
                    ),
                ).fetchone()
                if row is None:
                    raise OnlyIntegrationError("INTEGRATION_DRAFT_VERSION_CONFLICT")
        except OnlyIntegrationError:
            raise
        except psycopg.IntegrityError as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Draft update violates integrity") from exc
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Draft update failed") from exc
        return self.load_draft(integration_id)

    def load_draft(self, integration_id: OnlyIntegrationId) -> OnlyIntegrationDraft:
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    "SELECT integration_id::text, base_revision_fingerprint, type_descriptor_fingerprint, "
                    "type_descriptor_document, public_configuration_document, probe_configuration_document, "
                    "draft_version, draft_fingerprint, created_at, updated_at "
                    "FROM integration_draft WHERE integration_id = %s",
                    (integration_id.value,),
                ).fetchone()
                bindings = self._load_draft_bindings(connection, integration_id)
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Draft load failed") from exc
        if row is None:
            raise OnlyIntegrationError("INTEGRATION_DRAFT_NOT_FOUND")
        try:
            return OnlyIntegrationDraft.restore(
                integration_id=OnlyIntegrationId(str(row["integration_id"])),
                base_revision_fingerprint=cast(str | None, row["base_revision_fingerprint"]),
                type_descriptor_fingerprint=str(row["type_descriptor_fingerprint"]),
                type_descriptor_document=cast(Mapping[str, object], row["type_descriptor_document"]),
                public_configuration_document=cast(Mapping[str, object], row["public_configuration_document"]),
                probe_configuration_document=cast(Mapping[str, object] | None, row["probe_configuration_document"]),
                draft_version=int(cast(int, row["draft_version"])),
                draft_fingerprint=str(row["draft_fingerprint"]),
                created_at=cast(datetime, row["created_at"]),
                updated_at=cast(datetime, row["updated_at"]),
                secret_bindings=bindings,
            )
        except OnlyIntegrationError:
            raise
        except (TypeError, ValueError) as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Draft row is corrupt") from exc

    def replace_draft_secret_bindings(
        self,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        bindings: tuple[OnlyIntegrationSecretBinding, ...],
    ) -> OnlyIntegrationDraft:
        current = self.load_draft(integration_id)
        fingerprint = only_integration_draft_fingerprint(
            integration_id,
            current.base_revision_fingerprint,
            current.type_descriptor_fingerprint,
            current.type_descriptor_document,
            current.public_configuration_document,
            current.probe_configuration_document,
            bindings,
        )
        try:
            with self._connection_scope() as connection:
                self._validate_bindings(connection, integration_id, current.type_descriptor_document, bindings)
                row = connection.execute(
                    "UPDATE integration_draft SET draft_version = draft_version + 1, "
                    "draft_fingerprint = %s, updated_at = %s "
                    "WHERE integration_id = %s AND draft_version = %s RETURNING integration_id",
                    (fingerprint, self._now(), integration_id.value, expected_draft_version),
                ).fetchone()
                if row is None:
                    raise OnlyIntegrationError("INTEGRATION_DRAFT_VERSION_CONFLICT")
                connection.execute(
                    "DELETE FROM integration_draft_secret_binding WHERE integration_id = %s",
                    (integration_id.value,),
                )
                for binding in sorted(bindings, key=lambda item: item.field_id):
                    connection.execute(
                        "INSERT INTO integration_draft_secret_binding "
                        "(integration_id, field_id, credential_id, credential_generation) VALUES (%s, %s, %s, %s)",
                        (
                            integration_id.value,
                            binding.field_id,
                            binding.credential_id,
                            binding.credential_generation,
                        ),
                    )
        except OnlyIntegrationError:
            raise
        except psycopg.IntegrityError as exc:
            raise OnlyIntegrationError("INTEGRATION_SECRET_BINDING_INVALID") from exc
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Draft binding update failed") from exc
        return self.load_draft(integration_id)

    def replace_draft_state(
        self,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        public_configuration: Mapping[str, object],
        probe_configuration: Mapping[str, object] | None,
        bindings: tuple[OnlyIntegrationSecretBinding, ...],
        *,
        base_revision_fingerprint: str | None,
    ) -> OnlyIntegrationDraft:
        current = self.load_draft(integration_id)
        integration = self.load_integration(integration_id)
        if descriptor.type_id.value != integration.type_id:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Integration Type cannot change")
        candidate = OnlyIntegrationDraft.create(
            integration_id=integration_id,
            descriptor=descriptor,
            public_configuration=public_configuration,
            probe_configuration=probe_configuration,
            created_at=current.created_at,
            base_revision_fingerprint=base_revision_fingerprint,
        )
        fingerprint = only_integration_draft_fingerprint(
            integration_id,
            candidate.base_revision_fingerprint,
            candidate.type_descriptor_fingerprint,
            candidate.type_descriptor_document,
            candidate.public_configuration_document,
            candidate.probe_configuration_document,
            bindings,
        )
        try:
            with self._connection_scope() as connection:
                self._validate_bindings(connection, integration_id, candidate.type_descriptor_document, bindings)
                row = connection.execute(
                    "UPDATE integration_draft SET base_revision_fingerprint = %s, "
                    "type_descriptor_fingerprint = %s, type_descriptor_document = %s, "
                    "public_configuration_document = %s, probe_configuration_document = %s, "
                    "draft_version = draft_version + 1, draft_fingerprint = %s, updated_at = %s "
                    "WHERE integration_id = %s AND draft_version = %s RETURNING integration_id",
                    (
                        candidate.base_revision_fingerprint,
                        candidate.type_descriptor_fingerprint,
                        Json(only_integration_json_document(candidate.type_descriptor_document)),
                        Json(only_integration_json_document(candidate.public_configuration_document)),
                        None
                        if candidate.probe_configuration_document is None
                        else Json(only_integration_json_document(candidate.probe_configuration_document)),
                        fingerprint,
                        self._now(),
                        integration_id.value,
                        expected_draft_version,
                    ),
                ).fetchone()
                if row is None:
                    raise OnlyIntegrationError("INTEGRATION_DRAFT_VERSION_CONFLICT")
                connection.execute(
                    "DELETE FROM integration_draft_secret_binding WHERE integration_id = %s",
                    (integration_id.value,),
                )
                for binding in sorted(bindings, key=lambda item: item.field_id):
                    connection.execute(
                        "INSERT INTO integration_draft_secret_binding "
                        "(integration_id, field_id, credential_id, credential_generation) VALUES (%s, %s, %s, %s)",
                        (
                            integration_id.value,
                            binding.field_id,
                            binding.credential_id,
                            binding.credential_generation,
                        ),
                    )
        except OnlyIntegrationError:
            raise
        except psycopg.IntegrityError as exc:
            raise OnlyIntegrationError(
                "INTEGRATION_PERSISTENCE_CONFLICT", "Draft replacement violates integrity"
            ) from exc
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Draft replacement failed") from exc
        return self.load_draft(integration_id)

    def load_draft_secret_bindings(self, integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationSecretBinding, ...]:
        try:
            with self._connection_scope() as connection:
                return self._load_draft_bindings(connection, integration_id)
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Draft binding load failed") from exc

    def insert_revision(
        self,
        revision: OnlyIntegrationRevision,
        bindings: tuple[OnlyIntegrationSecretBinding, ...],
    ) -> OnlyIntegrationPutDisposition:
        clean = OnlyIntegrationRevision.restore(
            revision_fingerprint=revision.revision_fingerprint,
            integration_id=revision.integration_id,
            revision_sequence=revision.revision_sequence,
            type_id=revision.type_id,
            type_descriptor_fingerprint=revision.type_descriptor_fingerprint,
            type_descriptor_document=revision.type_descriptor_document,
            configuration_fingerprint=revision.configuration_fingerprint,
            configuration_document=revision.configuration_document,
            runtime_configuration_fingerprint=revision.runtime_configuration_fingerprint,
            probe_configuration_fingerprint=revision.probe_configuration_fingerprint,
            probe_configuration_document=revision.probe_configuration_document,
            secret_binding_fingerprint=revision.secret_binding_fingerprint,
            created_at=revision.created_at,
            secret_bindings=bindings,
        )
        try:
            with self._connection_scope() as connection:
                existing = self._load_revision(connection, clean.revision_fingerprint)
                if existing is not None:
                    return OnlyIntegrationPutDisposition.REUSED
                integration = self._load_integration_row(connection, clean.integration_id)
                if integration is None or str(integration["type_id"]) != clean.type_id:
                    raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Revision owner/type mismatch")
                self._validate_bindings(connection, clean.integration_id, clean.type_descriptor_document, bindings)
                inserted = connection.execute(
                    "INSERT INTO integration_revision "
                    "(revision_fingerprint, integration_id, revision_sequence, type_id, "
                    "type_descriptor_fingerprint, type_descriptor_document, configuration_fingerprint, "
                    "configuration_document, runtime_configuration_fingerprint, probe_configuration_fingerprint, "
                    "probe_configuration_document, secret_binding_fingerprint, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT DO NOTHING RETURNING revision_fingerprint",
                    (
                        clean.revision_fingerprint,
                        clean.integration_id.value,
                        clean.revision_sequence,
                        clean.type_id,
                        clean.type_descriptor_fingerprint,
                        Json(only_integration_json_document(clean.type_descriptor_document)),
                        clean.configuration_fingerprint,
                        Json(only_integration_json_document(clean.configuration_document)),
                        clean.runtime_configuration_fingerprint,
                        clean.probe_configuration_fingerprint,
                        None
                        if clean.probe_configuration_document is None
                        else Json(only_integration_json_document(clean.probe_configuration_document)),
                        clean.secret_binding_fingerprint,
                        clean.created_at,
                    ),
                ).fetchone()
                if inserted is not None:
                    for binding in sorted(bindings, key=lambda item: item.field_id):
                        connection.execute(
                            "INSERT INTO integration_revision_secret_binding "
                            "(revision_fingerprint, field_id, credential_id, credential_generation) "
                            "VALUES (%s, %s, %s, %s)",
                            (
                                clean.revision_fingerprint,
                                binding.field_id,
                                binding.credential_id,
                                binding.credential_generation,
                            ),
                        )
                actual = self._load_revision(connection, clean.revision_fingerprint)
        except OnlyIntegrationError:
            raise
        except psycopg.IntegrityError as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Revision constraint conflict") from exc
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Revision insert failed") from exc
        if actual is None:
            raise OnlyIntegrationError("INTEGRATION_REVISION_CORRUPT")
        return OnlyIntegrationPutDisposition.CREATED if inserted is not None else OnlyIntegrationPutDisposition.REUSED

    def load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision:
        try:
            with self._connection_scope() as connection:
                revision = self._load_revision(connection, revision_fingerprint)
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Revision load failed") from exc
        if revision is None:
            raise OnlyIntegrationError("INTEGRATION_REVISION_NOT_FOUND")
        return revision

    def list_revision_history(self, integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationRevision, ...]:
        try:
            with self._connection_scope() as connection:
                rows = connection.execute(
                    "SELECT revision_fingerprint FROM integration_revision WHERE integration_id = %s "
                    "ORDER BY revision_sequence, revision_fingerprint",
                    (integration_id.value,),
                ).fetchall()
                return tuple(self._require_revision(connection, str(row["revision_fingerprint"])) for row in rows)
        except OnlyIntegrationError:
            raise
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Revision history load failed") from exc

    def load_revision_secret_bindings(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]:
        try:
            with self._connection_scope() as connection:
                return self._load_revision_bindings(connection, revision_fingerprint)
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Revision binding load failed") from exc

    def set_current_revision(self, integration_id: OnlyIntegrationId, revision_fingerprint: str) -> None:
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    "UPDATE integration SET current_revision_fingerprint = %s, updated_at = %s "
                    "WHERE integration_id = %s RETURNING integration_id",
                    (revision_fingerprint, self._now(), integration_id.value),
                ).fetchone()
                if row is None:
                    raise OnlyIntegrationError("INTEGRATION_NOT_FOUND")
        except OnlyIntegrationError:
            raise
        except psycopg.IntegrityError as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "current Revision owner mismatch") from exc
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "current Revision update failed") from exc

    @contextmanager
    def _connection_scope(self) -> Iterator[psycopg.Connection[dict[str, object]]]:
        if self._connection is not None:
            yield self._connection
            return
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            yield connection

    @staticmethod
    def _load_integration_row(
        connection: psycopg.Connection[dict[str, object]], integration_id: OnlyIntegrationId
    ) -> dict[str, object] | None:
        return connection.execute(
            "SELECT integration_id::text, type_id FROM integration WHERE integration_id = %s",
            (integration_id.value,),
        ).fetchone()

    @staticmethod
    def _load_draft_bindings(
        connection: psycopg.Connection[dict[str, object]], integration_id: OnlyIntegrationId
    ) -> tuple[OnlyIntegrationSecretBinding, ...]:
        rows = connection.execute(
            "SELECT field_id, credential_id::text, credential_generation "
            "FROM integration_draft_secret_binding WHERE integration_id = %s ORDER BY field_id",
            (integration_id.value,),
        ).fetchall()
        return tuple(
            OnlyIntegrationSecretBinding(
                str(row["field_id"]),
                str(row["credential_id"]),
                int(cast(int, row["credential_generation"])),
            )
            for row in rows
        )

    @staticmethod
    def _load_revision_bindings(
        connection: psycopg.Connection[dict[str, object]], revision_fingerprint: str
    ) -> tuple[OnlyIntegrationSecretBinding, ...]:
        rows = connection.execute(
            "SELECT field_id, credential_id::text, credential_generation "
            "FROM integration_revision_secret_binding WHERE revision_fingerprint = %s ORDER BY field_id",
            (revision_fingerprint,),
        ).fetchall()
        return tuple(
            OnlyIntegrationSecretBinding(
                str(row["field_id"]),
                str(row["credential_id"]),
                int(cast(int, row["credential_generation"])),
            )
            for row in rows
        )

    @classmethod
    def _load_revision(
        cls, connection: psycopg.Connection[dict[str, object]], revision_fingerprint: str
    ) -> OnlyIntegrationRevision | None:
        row = connection.execute(
            "SELECT revision_fingerprint, integration_id::text, revision_sequence, type_id, "
            "type_descriptor_fingerprint, type_descriptor_document, configuration_fingerprint, "
            "configuration_document, runtime_configuration_fingerprint, probe_configuration_fingerprint, "
            "probe_configuration_document, secret_binding_fingerprint, created_at "
            "FROM integration_revision WHERE revision_fingerprint = %s",
            (revision_fingerprint,),
        ).fetchone()
        if row is None:
            return None
        bindings = cls._load_revision_bindings(connection, revision_fingerprint)
        try:
            return OnlyIntegrationRevision.restore(
                revision_fingerprint=str(row["revision_fingerprint"]),
                integration_id=OnlyIntegrationId(str(row["integration_id"])),
                revision_sequence=int(cast(int, row["revision_sequence"])),
                type_id=str(row["type_id"]),
                type_descriptor_fingerprint=str(row["type_descriptor_fingerprint"]),
                type_descriptor_document=cast(Mapping[str, object], row["type_descriptor_document"]),
                configuration_fingerprint=str(row["configuration_fingerprint"]),
                configuration_document=cast(Mapping[str, object], row["configuration_document"]),
                runtime_configuration_fingerprint=str(row["runtime_configuration_fingerprint"]),
                probe_configuration_fingerprint=cast(str | None, row["probe_configuration_fingerprint"]),
                probe_configuration_document=cast(Mapping[str, object] | None, row["probe_configuration_document"]),
                secret_binding_fingerprint=str(row["secret_binding_fingerprint"]),
                created_at=cast(datetime, row["created_at"]),
                secret_bindings=bindings,
            )
        except OnlyIntegrationError:
            raise
        except (TypeError, ValueError) as exc:
            raise OnlyIntegrationError("INTEGRATION_REVISION_CORRUPT") from exc

    @classmethod
    def _require_revision(
        cls, connection: psycopg.Connection[dict[str, object]], revision_fingerprint: str
    ) -> OnlyIntegrationRevision:
        revision = cls._load_revision(connection, revision_fingerprint)
        if revision is None:
            raise OnlyIntegrationError("INTEGRATION_REVISION_NOT_FOUND")
        return revision

    @staticmethod
    def _validate_bindings(
        connection: psycopg.Connection[dict[str, object]],
        integration_id: OnlyIntegrationId,
        descriptor_document: Mapping[str, object],
        bindings: tuple[OnlyIntegrationSecretBinding, ...],
    ) -> None:
        configuration = descriptor_document.get("configuration_contract")
        fields = configuration.get("fields") if isinstance(configuration, Mapping) else None
        if not isinstance(fields, (tuple, list)):
            raise OnlyIntegrationError("INTEGRATION_SECRET_BINDING_INVALID", "descriptor fields are invalid")
        secret_fields = {
            field.get("field_id") for field in fields if isinstance(field, Mapping) and field.get("secret") is True
        }
        if {binding.field_id for binding in bindings} - secret_fields:
            raise OnlyIntegrationError("INTEGRATION_SECRET_BINDING_INVALID", "field is not declared secret")
        if len({binding.field_id for binding in bindings}) != len(bindings):
            raise OnlyIntegrationError("INTEGRATION_SECRET_BINDING_INVALID", "field bindings must be unique")
        for binding in bindings:
            row = connection.execute(
                "SELECT credential_kind, subject_id, secret_name, generation FROM product_credential "
                "WHERE credential_id = %s FOR SHARE",
                (binding.credential_id,),
            ).fetchone()
            valid = (
                row is not None
                and row["credential_kind"] == "INTEGRATION_SECRET"
                and row["subject_id"] == integration_id.value
                and row["secret_name"] == binding.field_id
                and row["generation"] == binding.credential_generation
            )
            if not valid:
                raise OnlyIntegrationError("INTEGRATION_SECRET_BINDING_INVALID", "credential slot does not match")


__all__ = [name for name in globals() if name.startswith("Only")]
