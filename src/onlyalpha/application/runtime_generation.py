"""Application port for immutable formal-work RuntimeGeneration binding."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import NoReturn, Protocol, cast


@dataclass(frozen=True, slots=True)
class OnlyRuntimeWorkBindingEvidence:
    """Verified initial binding provenance plus its current execution eligibility."""

    work_id: str
    runtime_generation_fingerprint: str
    binding_kind: str
    binding_owner: str | None
    binding_actor: str
    binding_event_fingerprint: str
    binding_sequence: int
    active: bool

    def __post_init__(self) -> None:
        texts = (self.work_id, self.binding_actor)
        fingerprints = (self.runtime_generation_fingerprint, self.binding_event_fingerprint)
        if (
            any(type(value) is not str or not value.strip() for value in texts)
            or any(
                type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
                for value in fingerprints
            )
            or type(self.binding_kind) is not str
            or self.binding_kind not in {"NEW_WORK", "EXACT"}
            or (
                self.binding_kind == "NEW_WORK"
                and (type(self.binding_owner) is not str or not self.binding_owner.strip())
            )
            or (self.binding_kind == "EXACT" and self.binding_owner is not None)
            or type(self.binding_sequence) is not int
            or self.binding_sequence < 1
            or type(self.active) is not bool
        ):
            raise ValueError("RUNTIME_WORK_BINDING_EVIDENCE_INVALID")


class OnlyRuntimeGenerationWorkAuthority(Protocol):
    def bind_new_work(self, work_id: str, *, actor: str, occurred_at: datetime) -> object: ...

    def bind_new_work_exact(
        self, work_id: str, runtime_generation_fingerprint: str, *, owner: str, actor: str, occurred_at: datetime
    ) -> object: ...

    def bind_work_exact(
        self,
        work_id: str,
        runtime_generation_fingerprint: str,
        *,
        actor: str,
        occurred_at: datetime,
    ) -> object: ...

    def bind_derived_work(
        self,
        parent_work_id: str,
        child_work_id: str,
        *,
        actor: str,
        occurred_at: datetime,
    ) -> object: ...

    def require_new_work_generation(self, runtime_generation_fingerprint: str) -> object: ...

    def require_runtime_generation(self, runtime_generation_fingerprint: str) -> object: ...

    def require_historical_generation(self, generation_fingerprint: str) -> object: ...

    def hold_work_binding_evidence(self, work_id: str) -> AbstractContextManager[OnlyRuntimeWorkBindingEvidence]: ...

    def release_work(self, work_id: str, *, actor: str, occurred_at: datetime) -> object: ...

    def require_work_generation(self, work_id: str, process_generation_fingerprint: str) -> object: ...

    def require_work_binding(self, work_id: str) -> object: ...

    def require_work_binding_evidence(self, work_id: str) -> OnlyRuntimeWorkBindingEvidence: ...

    def close_new_work_exact(
        self,
        work_id: str,
        runtime_generation_fingerprint: str,
        *,
        owner: str,
        closure_reason: str,
        actor: str,
        occurred_at: datetime,
    ) -> OnlyRuntimeWorkAdmissionClosureEvidence: ...

    def require_work_admission_closure_evidence(self, work_id: str) -> OnlyRuntimeWorkAdmissionClosureEvidence: ...

    def work_ids_for_generation(self, process_generation_fingerprint: str) -> tuple[str, ...]: ...

    def verify_hosted_generation(self, generation_fingerprint: str) -> None: ...


class OnlyNoClaimRuntimeGenerationWorkAuthority:
    """Explicit lifecycle-only composition that can never admit or execute formal work."""

    @staticmethod
    def _unavailable() -> NoReturn:
        raise RuntimeError("RUNTIME_GENERATION_WORK_AUTHORITY_UNAVAILABLE")

    def bind_new_work(self, work_id: str, *, actor: str, occurred_at: datetime) -> object:
        del work_id, actor, occurred_at
        self._unavailable()

    def bind_new_work_exact(
        self, work_id: str, runtime_generation_fingerprint: str, *, owner: str, actor: str, occurred_at: datetime
    ) -> object:
        del work_id, runtime_generation_fingerprint, owner, actor, occurred_at
        self._unavailable()

    def bind_work_exact(
        self,
        work_id: str,
        runtime_generation_fingerprint: str,
        *,
        actor: str,
        occurred_at: datetime,
    ) -> object:
        del work_id, runtime_generation_fingerprint, actor, occurred_at
        self._unavailable()

    def bind_derived_work(
        self,
        parent_work_id: str,
        child_work_id: str,
        *,
        actor: str,
        occurred_at: datetime,
    ) -> object:
        del parent_work_id, child_work_id, actor, occurred_at
        self._unavailable()

    def require_new_work_generation(self, runtime_generation_fingerprint: str) -> object:
        del runtime_generation_fingerprint
        self._unavailable()

    def require_runtime_generation(self, runtime_generation_fingerprint: str) -> object:
        del runtime_generation_fingerprint
        self._unavailable()

    def require_historical_generation(self, generation_fingerprint: str) -> object:
        del generation_fingerprint
        self._unavailable()

    def hold_work_binding_evidence(self, work_id: str) -> AbstractContextManager[OnlyRuntimeWorkBindingEvidence]:
        del work_id
        self._unavailable()

    def release_work(self, work_id: str, *, actor: str, occurred_at: datetime) -> object:
        del work_id, actor, occurred_at
        self._unavailable()

    def require_work_generation(self, work_id: str, process_generation_fingerprint: str) -> object:
        del work_id, process_generation_fingerprint
        self._unavailable()

    def require_work_binding(self, work_id: str) -> object:
        del work_id
        self._unavailable()

    def require_work_binding_evidence(self, work_id: str) -> OnlyRuntimeWorkBindingEvidence:
        del work_id
        self._unavailable()

    def close_new_work_exact(
        self,
        work_id: str,
        runtime_generation_fingerprint: str,
        *,
        owner: str,
        closure_reason: str,
        actor: str,
        occurred_at: datetime,
    ) -> OnlyRuntimeWorkAdmissionClosureEvidence:
        del work_id, runtime_generation_fingerprint, owner, closure_reason, actor, occurred_at
        self._unavailable()

    def require_work_admission_closure_evidence(self, work_id: str) -> OnlyRuntimeWorkAdmissionClosureEvidence:
        del work_id
        self._unavailable()

    def work_ids_for_generation(self, process_generation_fingerprint: str) -> tuple[str, ...]:
        del process_generation_fingerprint
        return ()

    def verify_hosted_generation(self, generation_fingerprint: str) -> None:
        del generation_fingerprint
        self._unavailable()


@dataclass(frozen=True, slots=True)
class OnlyRuntimeWorkAdmissionClosureEvidence:
    work_id: str
    runtime_generation_fingerprint: str
    binding_owner: str
    closure_reason: str
    closure_actor: str
    closure_event_fingerprint: str
    closure_sequence: int

    def __post_init__(self) -> None:
        try:
            OnlyRuntimeWorkBindingEvidence(
                self.work_id,
                self.runtime_generation_fingerprint,
                "NEW_WORK",
                self.binding_owner,
                self.closure_actor,
                self.closure_event_fingerprint,
                self.closure_sequence,
                True,
            )
            if type(self.closure_reason) is not str or not self.closure_reason.strip():
                raise ValueError("empty closure reason")
        except ValueError as exc:
            raise ValueError("RUNTIME_WORK_ADMISSION_CLOSURE_INVALID") from exc

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> OnlyRuntimeWorkAdmissionClosureEvidence:
        if type(payload) is not dict or set(payload) != set(cls.__dataclass_fields__):
            raise ValueError("RUNTIME_WORK_ADMISSION_CLOSURE_INVALID")
        return cls(
            cast(str, payload["work_id"]),
            cast(str, payload["runtime_generation_fingerprint"]),
            cast(str, payload["binding_owner"]),
            cast(str, payload["closure_reason"]),
            cast(str, payload["closure_actor"]),
            cast(str, payload["closure_event_fingerprint"]),
            cast(int, payload["closure_sequence"]),
        )


__all__ = [
    "OnlyNoClaimRuntimeGenerationWorkAuthority",
    "OnlyRuntimeGenerationWorkAuthority",
    "OnlyRuntimeWorkBindingEvidence",
    "OnlyRuntimeWorkAdmissionClosureEvidence",
]
