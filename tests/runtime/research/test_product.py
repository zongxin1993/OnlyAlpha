from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.runtime.research import OnlyResearchRuntimeState
from onlyalpha.runtime.result import OnlyRuntimeResultStatus
from tests.runtime.research.support import sweep_only_workload_case, workload_case


def test_engine_runs_exact_research_workload_and_fresh_engine_reuses_authorities(tmp_path: Path) -> None:
    first_engine, workload = workload_case(tmp_path)
    runtime_id = first_engine.add_research_workload(workload)
    validation = first_engine.validate()
    assert validation.valid and validation.cluster_count == 0 and validation.runtime_group_count == 1
    first_engine.initialize()
    assert first_engine.snapshot().plugin_resources == ()
    first_engine.start()
    first = first_engine.run_runtime(runtime_id)
    assert first.status is OnlyRuntimeResultStatus.COMPLETED
    assert first.direct_job_outcomes[0].disposition.value == "EXECUTED"
    assert first_engine.runtime_sessions[0].bound_cluster_ids == ()
    assert first.to_dict()["failure"] is None
    first_engine.stop()
    first_engine.close()

    second_engine, repeated = workload_case(tmp_path)
    repeated_id = second_engine.add_research_workload(repeated)
    second_engine.initialize()
    second_engine.start()
    second = second_engine.run_runtime(repeated_id)
    assert all(item.disposition.value == "REUSED" for item in second.direct_job_outcomes)
    assert all(item.disposition.value == "REUSED" for item in second.statistics_outcomes)
    assert second.research_result_fingerprint == first.research_result_fingerprint
    assert second.artifact_content_fingerprint == first.artifact_content_fingerprint
    assert second.determinism_fingerprint == first.determinism_fingerprint
    second_engine.stop()


def test_research_runtime_lifecycle_is_finite_and_run_once(tmp_path: Path) -> None:
    engine, workload = workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    assert runtime.state is OnlyResearchRuntimeState.READY
    runtime.initialize()
    engine.start()
    assert engine.run_runtime(runtime_id).status is OnlyRuntimeResultStatus.COMPLETED
    with pytest.raises(OnlyLifecycleError, match="cannot run from"):
        engine.run_runtime(runtime_id)
    engine.stop()
    assert runtime.state is OnlyResearchRuntimeState.CLOSED
    runtime.close()
    with pytest.raises(OnlyLifecycleError, match="cannot initialize"):
        runtime.initialize()


def test_research_runtime_rejects_start_before_initialize(tmp_path: Path) -> None:
    engine, workload = workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    plan = engine._research_plans[str(runtime_id)]  # type: ignore[attr-defined]
    build = engine._require_services().assembler.build(plan, tmp_path)  # type: ignore[attr-defined]
    assert build.runtime is not None
    with pytest.raises(OnlyLifecycleError, match="cannot start"):
        build.runtime.start()
    build.runtime.close()


def test_unknown_runtime_and_wait_capabilities_fail_formally(tmp_path: Path) -> None:
    engine, workload = workload_case(tmp_path)
    engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    with pytest.raises(OnlyLifecycleError, match="RUNTIME_NOT_FOUND"):
        engine.run_runtime("unknown")
    with pytest.raises(OnlyLifecycleError, match="finite and cannot wait"):
        engine.wait(0)
    engine.stop()


def test_fresh_process_reentry_preserves_semantic_and_determinism_identity(tmp_path: Path) -> None:
    program = (
        "import json,sys; from pathlib import Path; "
        "from tests.runtime.research.support import workload_case; "
        "e,w=workload_case(Path(sys.argv[1])); r=e.add_research_workload(w); "
        "e.initialize(); e.start(); o=e.run_runtime(r); e.stop(); "
        "print(json.dumps({'result':o.research_result_fingerprint,'artifact':o.artifact_content_fingerprint,"
        "'determinism':o.determinism_fingerprint,'dispositions':[x.disposition.value for x in o.direct_job_outcomes]}))"
    )
    first = json.loads(subprocess.check_output([sys.executable, "-c", program, str(tmp_path)], text=True))
    second = json.loads(subprocess.check_output([sys.executable, "-c", program, str(tmp_path)], text=True))
    assert first["dispositions"] == ["EXECUTED", "EXECUTED"]
    assert second["dispositions"] == ["REUSED", "REUSED"]
    assert {key: first[key] for key in ("result", "artifact", "determinism")} == {
        key: second[key] for key in ("result", "artifact", "determinism")
    }


def test_sweep_only_workload_preserves_sweep_execution_outcome(tmp_path: Path) -> None:
    engine, workload = sweep_only_workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    result = engine.run_runtime(runtime_id)
    assert result.status is OnlyRuntimeResultStatus.COMPLETED
    assert result.direct_job_outcomes == ()
    assert len(result.sweep_outcomes) == 2
    assert all(item.total_cells == 1 and item.cells[0].ordinal == 0 for item in result.sweep_outcomes)
    assert result.to_dict()["sweep_outcomes"][0]["executed_count"] == 1  # type: ignore[index]
    engine.stop()
