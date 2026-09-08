"""Transport-neutral Product Command Admission and Receipt authority contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandReceipt,
)


class OnlyProductCommandAuthorityError(RuntimeError):
    code = "PRODUCT_COMMAND_AUTHORITY_ERROR"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}")


class OnlyProductCommandConflictError(OnlyProductCommandAuthorityError):
    code = "PRODUCT_COMMAND_CONFLICT"


class OnlyProductCommandAdmissionCorruptError(OnlyProductCommandAuthorityError):
    code = "PRODUCT_COMMAND_ADMISSION_CORRUPT"


class OnlyProductCommandReceiptCorruptError(OnlyProductCommandAuthorityError):
    code = "PRODUCT_COMMAND_RECEIPT_CORRUPT"


class OnlyProductCommandBindingMismatchError(OnlyProductCommandAuthorityError):
    code = "PRODUCT_COMMAND_BINDING_MISMATCH"


class OnlyProductCommandAuthorityUnavailableError(OnlyProductCommandAuthorityError):
    code = "PRODUCT_COMMAND_AUTHORITY_UNAVAILABLE"


class OnlyProductCommandPutDisposition(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"


class OnlyProductCommandBindingState(StrEnum):
    NONE = "NONE"
    ADMITTED_NO_OUTCOME = "ADMITTED_NO_OUTCOME"
    VERIFIED_ACCEPTED = "VERIFIED_ACCEPTED"


@dataclass(frozen=True, slots=True)
class OnlyProductCommandBindingVerification:
    state: OnlyProductCommandBindingState
    admission: OnlyProductCommandAdmissionV1 | None = None
    receipt: OnlyProductCommandReceipt | None = None

    def __post_init__(self) -> None:
        expected = {
            OnlyProductCommandBindingState.NONE: (False, False),
            OnlyProductCommandBindingState.ADMITTED_NO_OUTCOME: (True, False),
            OnlyProductCommandBindingState.VERIFIED_ACCEPTED: (True, True),
        }[self.state]
        if (self.admission is not None, self.receipt is not None) != expected:
            raise ValueError("Product Command binding verification shape is invalid")


class OnlyProductCommandAdmissionAuthority(Protocol):
    def admit_exact(self, admission: OnlyProductCommandAdmissionV1) -> OnlyProductCommandPutDisposition: ...

    def load_admission(self, command_id: OnlyProductCommandId) -> OnlyProductCommandAdmissionV1 | None: ...


class OnlyProductCommandReceiptAuthority(Protocol):
    def load_verified_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None: ...

    def put_verified_receipt(self, receipt: OnlyProductCommandReceipt) -> OnlyProductCommandPutDisposition: ...


def only_verify_product_command_binding(
    admission: OnlyProductCommandAdmissionV1,
    receipt: OnlyProductCommandReceipt,
) -> None:
    if (
        receipt.command_id != admission.command_id
        or receipt.command_kind is not admission.command_kind
        or receipt.command_fingerprint != admission.command_fingerprint
        or receipt.schema_version != admission.schema_version
    ):
        raise OnlyProductCommandBindingMismatchError(admission.command_id.value)


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
