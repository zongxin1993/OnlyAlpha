"""Application port for immutable formal-work RuntimeGeneration binding."""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn, Protocol


class OnlyRuntimeGenerationWorkAuthority(Protocol):
    def bind_new_work(self, work_id: str, *, actor: str, occurred_at: datetime) -> object: ...

    def release_work(self, work_id: str, *, actor: str, occurred_at: datetime) -> object: ...

    def require_work_generation(self, work_id: str, process_generation_fingerprint: str) -> object: ...

    def require_work_binding(self, work_id: str) -> object: ...

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

    def release_work(self, work_id: str, *, actor: str, occurred_at: datetime) -> object:
        del work_id, actor, occurred_at
        self._unavailable()

    def require_work_generation(self, work_id: str, process_generation_fingerprint: str) -> object:
        del work_id, process_generation_fingerprint
        self._unavailable()

    def require_work_binding(self, work_id: str) -> object:
        del work_id
        self._unavailable()

    def work_ids_for_generation(self, process_generation_fingerprint: str) -> tuple[str, ...]:
        del process_generation_fingerprint
        return ()

    def verify_hosted_generation(self, generation_fingerprint: str) -> None:
        del generation_fingerprint
        self._unavailable()


__all__ = ["OnlyNoClaimRuntimeGenerationWorkAuthority", "OnlyRuntimeGenerationWorkAuthority"]
