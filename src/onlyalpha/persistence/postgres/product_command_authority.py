"""PostgreSQL implementation of the global Product Command Authorities."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

import psycopg

from onlyalpha.application.product_command_authority import (
    OnlyProductCommandAdmissionCorruptError,
    OnlyProductCommandAuthorityUnavailableError,
    OnlyProductCommandBindingState,
    OnlyProductCommandBindingVerification,
    OnlyProductCommandConflictError,
    OnlyProductCommandPutDisposition,
    OnlyProductCommandReceiptCorruptError,
    only_verify_product_command_binding,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)

from .config import OnlyPostgresOperationalConnectionOptions


class OnlyPostgresProductCommandAuthority:
    """One PostgreSQL authority for immutable Admission and accepted Receipt facts."""

    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def admit_exact(self, admission: OnlyProductCommandAdmissionV1) -> OnlyProductCommandPutDisposition:
        try:
            with psycopg.connect(self._dsn) as connection:
                return self.insert_or_verify_admission(connection, admission)
        except (OnlyProductCommandConflictError, OnlyProductCommandAdmissionCorruptError):
            raise
        except psycopg.Error as exc:
            raise OnlyProductCommandAuthorityUnavailableError(admission.command_id.value) from exc

    def load_admission(self, command_id: OnlyProductCommandId) -> OnlyProductCommandAdmissionV1 | None:
        try:
            with psycopg.connect(self._dsn) as connection:
                return self.load_admission_in_transaction(connection, command_id)
        except OnlyProductCommandAdmissionCorruptError:
            raise
        except psycopg.Error as exc:
            raise OnlyProductCommandAuthorityUnavailableError(command_id.value) from exc

    def load_verified_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None:
        try:
            with psycopg.connect(self._dsn) as connection:
                return self.load_verified_receipt_in_transaction(connection, command_id)
        except (OnlyProductCommandAdmissionCorruptError, OnlyProductCommandReceiptCorruptError):
            raise
        except psycopg.Error as exc:
            raise OnlyProductCommandAuthorityUnavailableError(command_id.value) from exc

    def put_verified_receipt(self, receipt: OnlyProductCommandReceipt) -> OnlyProductCommandPutDisposition:
        try:
            with psycopg.connect(self._dsn) as connection:
                self.lock_command(connection, receipt.command_id)
                return self.insert_verified_receipt(connection, receipt)
        except (
            OnlyProductCommandAdmissionCorruptError,
            OnlyProductCommandConflictError,
            OnlyProductCommandReceiptCorruptError,
        ):
            raise
        except psycopg.Error as exc:
            raise OnlyProductCommandAuthorityUnavailableError(receipt.command_id.value) from exc

    def verify_binding(self, command_id: OnlyProductCommandId) -> OnlyProductCommandBindingVerification:
        try:
            with psycopg.connect(self._dsn) as connection:
                admission = self.load_admission_in_transaction(connection, command_id)
                receipt = self.load_receipt_in_transaction(connection, command_id)
                if admission is None:
                    if receipt is not None:
                        raise OnlyProductCommandReceiptCorruptError(command_id.value)
                    return OnlyProductCommandBindingVerification(OnlyProductCommandBindingState.NONE)
                if receipt is None:
                    return OnlyProductCommandBindingVerification(
                        OnlyProductCommandBindingState.ADMITTED_NO_OUTCOME,
                        admission,
                    )
                only_verify_product_command_binding(admission, receipt)
                return OnlyProductCommandBindingVerification(
                    OnlyProductCommandBindingState.VERIFIED_ACCEPTED,
                    admission,
                    receipt,
                )
        except (
            OnlyProductCommandAdmissionCorruptError,
            OnlyProductCommandReceiptCorruptError,
        ):
            raise
        except psycopg.Error as exc:
            raise OnlyProductCommandAuthorityUnavailableError(command_id.value) from exc

    @staticmethod
    def lock_command(connection: psycopg.Connection[object], command_id: OnlyProductCommandId) -> None:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (command_id.value,),
        )

    @classmethod
    def insert_or_verify_admission(
        cls,
        connection: psycopg.Connection[object],
        admission: OnlyProductCommandAdmissionV1,
    ) -> OnlyProductCommandPutDisposition:
        cls.lock_command(connection, admission.command_id)
        existing_admission = cls.load_admission_in_transaction(connection, admission.command_id)
        existing_receipt = cls.load_receipt_in_transaction(connection, admission.command_id)
        if existing_admission is None and existing_receipt is not None:
            raise OnlyProductCommandReceiptCorruptError(admission.command_id.value)
        if existing_admission is not None:
            if existing_admission != admission:
                raise OnlyProductCommandConflictError(admission.command_id.value)
            return OnlyProductCommandPutDisposition.REUSED
        inserted = connection.execute(
            """INSERT INTO product_command_admission
            (command_id, command_kind, command_fingerprint, schema_version)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (command_id) DO NOTHING
            RETURNING command_id""",
            (
                admission.command_id.value,
                admission.command_kind.value,
                admission.command_fingerprint,
                admission.schema_version,
            ),
        ).fetchone()
        if cls.load_receipt_in_transaction(connection, admission.command_id) is not None:
            raise OnlyProductCommandReceiptCorruptError(admission.command_id.value)
        actual = cls.load_admission_in_transaction(connection, admission.command_id)
        if actual is None:
            raise OnlyProductCommandAdmissionCorruptError(admission.command_id.value)
        if actual != admission:
            raise OnlyProductCommandConflictError(admission.command_id.value)
        if inserted is None:
            raise OnlyProductCommandAdmissionCorruptError(admission.command_id.value)
        return OnlyProductCommandPutDisposition.CREATED

    @staticmethod
    def load_admission_in_transaction(
        connection: psycopg.Connection[object],
        command_id: OnlyProductCommandId,
    ) -> OnlyProductCommandAdmissionV1 | None:
        row = connection.execute(
            """SELECT command_id::text, command_kind, command_fingerprint, schema_version
            FROM product_command_admission WHERE command_id = %s""",
            (command_id.value,),
        ).fetchone()
        if row is None:
            return None
        try:
            values = _row_values(
                row,
                ("command_id", "command_kind", "command_fingerprint", "schema_version"),
            )
            return OnlyProductCommandAdmissionV1(
                OnlyProductCommandId(str(values[0])),
                OnlyProductCommandKind(str(values[1])),
                str(values[2]),
                int(cast(int, values[3])),
            )
        except (TypeError, ValueError) as exc:
            raise OnlyProductCommandAdmissionCorruptError(command_id.value) from exc

    @classmethod
    def load_verified_receipt_in_transaction(
        cls,
        connection: psycopg.Connection[object],
        command_id: OnlyProductCommandId,
    ) -> OnlyProductCommandReceipt | None:
        admission = cls.load_admission_in_transaction(connection, command_id)
        receipt = cls.load_receipt_in_transaction(connection, command_id)
        if receipt is None:
            return None
        if admission is None:
            raise OnlyProductCommandReceiptCorruptError(command_id.value)
        try:
            only_verify_product_command_binding(admission, receipt)
        except Exception as exc:
            raise OnlyProductCommandReceiptCorruptError(command_id.value) from exc
        return receipt

    @staticmethod
    def load_receipt_in_transaction(
        connection: psycopg.Connection[object],
        command_id: OnlyProductCommandId,
    ) -> OnlyProductCommandReceipt | None:
        row = connection.execute(
            """SELECT command_id::text, command_kind, command_fingerprint, outcome_kind,
                      outcome_id, accepted_at, schema_version
            FROM product_command_receipt WHERE command_id = %s""",
            (command_id.value,),
        ).fetchone()
        if row is None:
            return None
        try:
            values = _row_values(
                row,
                (
                    "command_id",
                    "command_kind",
                    "command_fingerprint",
                    "outcome_kind",
                    "outcome_id",
                    "accepted_at",
                    "schema_version",
                ),
            )
            return OnlyProductCommandReceipt(
                OnlyProductCommandId(str(values[0])),
                OnlyProductCommandKind(str(values[1])),
                str(values[2]),
                OnlyProductCommandOutcomeRef(
                    OnlyProductCommandOutcomeKind(str(values[3])),
                    str(values[4]),
                ),
                cast(datetime, values[5]),
                int(cast(int, values[6])),
            )
        except (TypeError, ValueError) as exc:
            raise OnlyProductCommandReceiptCorruptError(command_id.value) from exc

    @classmethod
    def insert_verified_receipt(
        cls,
        connection: psycopg.Connection[object],
        receipt: OnlyProductCommandReceipt,
    ) -> OnlyProductCommandPutDisposition:
        admission = cls.load_admission_in_transaction(connection, receipt.command_id)
        if admission is None:
            raise OnlyProductCommandReceiptCorruptError(receipt.command_id.value)
        try:
            only_verify_product_command_binding(admission, receipt)
        except Exception as exc:
            raise OnlyProductCommandReceiptCorruptError(receipt.command_id.value) from exc
        inserted = connection.execute(
            """INSERT INTO product_command_receipt
            (command_id, command_kind, command_fingerprint, outcome_kind, outcome_id, accepted_at, schema_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (command_id) DO NOTHING
            RETURNING command_id""",
            (
                receipt.command_id.value,
                receipt.command_kind.value,
                receipt.command_fingerprint,
                receipt.outcome_ref.kind.value,
                receipt.outcome_ref.outcome_id,
                receipt.accepted_at,
                receipt.schema_version,
            ),
        ).fetchone()
        actual = cls.load_verified_receipt_in_transaction(connection, receipt.command_id)
        if actual is None:
            raise OnlyProductCommandReceiptCorruptError(receipt.command_id.value)
        if actual != receipt:
            raise OnlyProductCommandConflictError(receipt.command_id.value)
        return (
            OnlyProductCommandPutDisposition.CREATED
            if inserted is not None
            else OnlyProductCommandPutDisposition.REUSED
        )


def _row_values(row: object, names: tuple[str, ...]) -> tuple[object, ...]:
    if isinstance(row, Mapping):
        mapping = cast(Mapping[str, object], row)
        return tuple(mapping[name] for name in names)
    return cast(tuple[object, ...], row)


__all__ = ["OnlyPostgresProductCommandAuthority"]
