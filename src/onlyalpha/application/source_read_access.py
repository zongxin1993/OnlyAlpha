"""Immutable local human read grants; not market truth or Command permission."""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onlyalpha.application.market_data_product import (
        OnlyMarketDataSourceReferenceV1,
        OnlyMarketDataSourceSelectionV1,
    )


class OnlySourceReadAccessError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OnlySourceReadPermission(StrEnum):
    CLOSED_HISTORY = "CLOSED_HISTORY"
    REALTIME_PREVIEW = "REALTIME_PREVIEW"


@dataclass(frozen=True, slots=True)
class OnlySourceReadGrant:
    integration_id: str
    integration_revision_fingerprint: str
    expected_type_id: str
    source_id: str
    environment: str
    permissions: tuple[OnlySourceReadPermission, ...]

    def __post_init__(self) -> None:
        for value in (self.integration_id, self.expected_type_id, self.source_id, self.environment):
            if not isinstance(value, str) or not value or len(value) > 256 or "*" in value or value.strip() != value:
                raise OnlySourceReadAccessError("LOCAL_READ_CONFIG_INVALID")
        if not re.fullmatch(r"[0-9a-f]{64}", self.integration_revision_fingerprint):
            raise OnlySourceReadAccessError("LOCAL_READ_CONFIG_INVALID")
        if (
            not self.permissions
            or not isinstance(self.permissions, tuple)
            or any(not isinstance(item, OnlySourceReadPermission) for item in self.permissions)
            or len(set(self.permissions)) != len(self.permissions)
        ):
            raise OnlySourceReadAccessError("LOCAL_READ_CONFIG_INVALID")

    def matches_reference(self, reference: OnlyMarketDataSourceReferenceV1) -> bool:
        return (
            reference.integration_id == self.integration_id
            and reference.integration_revision_fingerprint == self.integration_revision_fingerprint
            and reference.expected_type_id == self.expected_type_id
        )


@dataclass(frozen=True, slots=True, repr=False)
class OnlySourceReadSession:
    """In-process identity, issued only by the configured credential authority."""

    authority: OnlySourceReadAuthority = field(repr=False)
    _issuance: object = field(repr=False)

    def check_active(self) -> None:
        self.authority.check_session(self)

    def require_reference(
        self, reference: OnlyMarketDataSourceReferenceV1, permission: OnlySourceReadPermission
    ) -> OnlySourceReadGrant:
        self.check_active()
        matches = tuple(item for item in self.authority.grants if item.matches_reference(reference))
        if len(matches) != 1 or permission not in matches[0].permissions:
            raise OnlySourceReadAccessError("LOCAL_READ_FORBIDDEN")
        return matches[0]

    def require_selection(
        self, selection: OnlyMarketDataSourceSelectionV1, permission: OnlySourceReadPermission
    ) -> None:
        from onlyalpha.application.market_data_product import (
            OnlyMarketDataSourceReferenceV1,
            OnlyMarketDataSourceSelectionV1,
        )

        if not isinstance(selection, OnlyMarketDataSourceSelectionV1) or any(
            not isinstance(value, str) or not value
            for value in (
                selection.integration_id,
                selection.integration_revision_fingerprint,
                selection.type_id,
                selection.source_id,
                selection.environment,
            )
        ):
            raise OnlySourceReadAccessError("LOCAL_READ_PROOF_UNAVAILABLE")

        grant = self.require_reference(
            OnlyMarketDataSourceReferenceV1(
                selection.integration_id, selection.integration_revision_fingerprint, selection.type_id
            ),
            permission,
        )
        if selection.source_id != grant.source_id or selection.environment != grant.environment:
            raise OnlySourceReadAccessError("LOCAL_READ_FORBIDDEN")


class OnlySourceReadAuthority:
    """One startup composition. Withdrawal is irreversible; replacement needs a new process."""

    def __init__(self, subject_id: str, bearer_sha256: str, grants: tuple[OnlySourceReadGrant, ...]) -> None:
        if (
            not isinstance(subject_id, str)
            or not subject_id
            or len(subject_id) > 128
            or subject_id.strip() != subject_id
            or not re.fullmatch(r"[0-9a-f]{64}", bearer_sha256)
            or not 0 <= len(grants) <= 32
            or not isinstance(grants, tuple)
            or any(not isinstance(item, OnlySourceReadGrant) for item in grants)
        ):
            raise OnlySourceReadAccessError("LOCAL_READ_CONFIG_INVALID")
        references = {(g.integration_id, g.integration_revision_fingerprint, g.expected_type_id) for g in grants}
        if len(references) != len(grants):
            raise OnlySourceReadAccessError("LOCAL_READ_CONFIG_INVALID")
        self._subject_id = subject_id
        self._bearer_sha256 = bearer_sha256
        self._grants = grants
        self._issuance = object()
        self._lock = threading.Lock()
        self._active = True

    @property
    def grants(self) -> tuple[OnlySourceReadGrant, ...]:
        return self._grants

    def authenticate(self, authorization: str) -> OnlySourceReadSession:
        if not re.fullmatch(r"Bearer [0-9a-f]{64}", authorization):
            raise OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED")
        digest = hashlib.sha256(authorization[7:].encode("ascii")).hexdigest()
        if not secrets.compare_digest(digest, self._bearer_sha256):
            raise OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED")
        session = OnlySourceReadSession(self, self._issuance)
        session.check_active()
        return session

    def check_session(self, session: OnlySourceReadSession) -> None:
        with self._lock:
            if not self._active or session.authority is not self or session._issuance is not self._issuance:
                raise OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED")

    def withdraw(self) -> None:
        """Ingress must fence outbound sends before calling this; not a global deployment ACK."""
        with self._lock:
            self._active = False
