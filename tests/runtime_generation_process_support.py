"""Test-owned RuntimeGeneration composition for non-generation process E2E lanes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from tests.runtime_generation_support import only_ready_test_generation


def only_prepare_test_process_generation(
    root: Path,
    *,
    work_ids: tuple[str, ...] = (),
) -> tuple[Path, str]:
    authority = OnlyRuntimeGenerationRegistry(root)
    now = datetime(2026, 9, 5, tzinfo=UTC)
    generation = only_ready_test_generation(authority, "e", now)
    authority.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="test-operator",
        occurred_at=now + timedelta(seconds=1),
    )
    for index, work_id in enumerate(work_ids, start=2):
        authority.bind_new_work(
            work_id,
            actor="test-product-admission",
            occurred_at=now + timedelta(seconds=index),
        )
    return root, generation


def only_allow_unsealed_test_process_generation() -> None:
    """Keep the production CLI sealed while test-owned process E2E uses a contract fake."""

    def verify_test_generation(self: OnlyRuntimeGenerationRegistry, fingerprint: str) -> None:
        evidence = self.load_validation_evidence(fingerprint)
        if not evidence.verifies(self.load_manifest(fingerprint)):
            raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH")

    OnlyRuntimeGenerationRegistry.verify_hosted_generation = verify_test_generation


__all__ = ["only_allow_unsealed_test_process_generation", "only_prepare_test_process_generation"]
