from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from tests.application.test_chart_calculation_admission import NOW
from tests.runtime_support.generation_support import only_ready_test_generation


def test_handoff_proof_holds_cross_process_lifecycle_lock(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = only_ready_test_generation(registry, "a", NOW)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="human", occurred_at=NOW)
    registry.bind_new_work_exact("work", generation, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW)
    original = registry.require_work_binding_evidence("work")
    code = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print('LIFECYCLE_BLOCKED', flush=True)
else:
    raise AssertionError('handoff did not hold the owning lifecycle lock')
os.close(fd)
"""
    with registry.hold_work_binding_evidence("work") as proof:
        assert proof == original
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path / ".generation-authority.lock")],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "LIFECYCLE_BLOCKED"
        assert registry.require_runtime_generation(generation).runtime_generation_fingerprint == generation
    registry.release_work("work", actor="human", occurred_at=NOW)
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_MISMATCH"):
        with registry.hold_work_binding_evidence("work"):
            pytest.fail("inactive work acquired handoff permission")


def test_bound_work_guard_survives_activation_switch_but_not_retirement(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    original = only_ready_test_generation(registry, "a", NOW)
    next_generation = only_ready_test_generation(registry, "b", NOW)
    registry.activate_for_new_work(expected_current=None, target=original, actor="human", occurred_at=NOW)
    registry.bind_new_work_exact("work", original, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW)
    registry.activate_for_new_work(expected_current=original, target=next_generation, actor="human", occurred_at=NOW)
    with registry.hold_work_binding_evidence("work") as proof:
        assert proof.runtime_generation_fingerprint == original
    registry.release_work("work", actor="human", occurred_at=NOW)
    registry.retire(original, actor="human", occurred_at=NOW)
    assert registry.require_historical_generation(original).runtime_generation_fingerprint == original
    with pytest.raises(ValueError):
        with registry.hold_work_binding_evidence("work"):
            pytest.fail("retired work acquired admission permission")
