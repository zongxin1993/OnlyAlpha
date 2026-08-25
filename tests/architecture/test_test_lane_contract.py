from __future__ import annotations

from pathlib import Path

import pytest

from scripts.pytest_layering import CONCERN_MARKERS, LAYER_MARKERS, path_concerns, path_layer
from scripts.test_suite import LANES, OnlyTestLane

pytestmark = pytest.mark.architecture


def test_layer_and_concern_taxonomies_are_orthogonal() -> None:
    assert LAYER_MARKERS == {"unit", "contract", "architecture", "integration", "scenario"}
    assert CONCERN_MARKERS == {
        "recovery",
        "sim_recovery",
        "conformance",
        "external",
        "performance",
        "exhaustive",
        "miniqmt",
    }
    assert LAYER_MARKERS.isdisjoint(CONCERN_MARKERS)


@pytest.mark.parametrize(
    ("path", "layer"),
    (
        ("tests/architecture/test_boundary.py", "architecture"),
        ("tests/scenario/test_run.py", "scenario"),
        ("tests/integration/test_engine_recovery.py", "integration"),
        ("packages/provider/plugin/tests/test_adapter.py", "contract"),
        ("tests/order/test_order.py", "unit"),
    ),
)
def test_every_path_resolves_to_exactly_one_layer(path: str, layer: str) -> None:
    assert path_layer(Path(path)) == layer


def test_recovery_and_conformance_are_independent_concerns() -> None:
    assert path_concerns(Path("tests/integration/test_engine_checkpoint_restart.py")) == {"recovery"}
    assert path_concerns(Path("tests/conformance/cn_a_share_cash/test_rules.py")) == {"conformance"}


def test_lane_expressions_keep_concerns_separate() -> None:
    core = LANES[OnlyTestLane.CORE_FULL].expression
    assert core.startswith("not (")
    assert all(concern in core for concern in ("recovery", "conformance", "exhaustive"))
    assert LANES[OnlyTestLane.RECOVERY].expression == "recovery and not external and not exhaustive"
    assert LANES[OnlyTestLane.SIM_RECOVERY].expression == "sim_recovery and not external and not exhaustive"
    assert LANES[OnlyTestLane.ASHARE].expression == "conformance and not external and not exhaustive"
    assert LANES[OnlyTestLane.EXHAUSTIVE].expression == "exhaustive and not external"


def test_every_regular_lane_uses_one_workspace_pytest_session() -> None:
    for name, lane in LANES.items():
        if name is OnlyTestLane.MINIQMT_LOCAL:
            continue
        assert lane.paths


def test_architecture_lane_is_the_single_stable_repository_gate() -> None:
    lane = LANES[OnlyTestLane.ARCHITECTURE]
    assert lane.paths == ("tests/architecture",)
    assert lane.expression == "architecture"
    assert lane.workers == "0"
    assert lane.dist == "no"


def test_normal_ci_directly_runs_the_canonical_architecture_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "- run: uv run python scripts/test_suite.py architecture" in workflow
    assert "ARCHITECTURE_RESULT: ${{ needs.architecture.result }}" in workflow


def test_research_job_lane_owns_application_contract_and_architecture_gate() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_JOB]
    assert lane.paths == (
        "tests/research/job",
        "tests/architecture/test_research_calculation_boundaries.py",
    )
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/research/job"' in source
    assert '"research-job-coverage"' in source


def test_research_factor_lane_owns_semantics_execution_architecture_and_full_coverage() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_FACTOR]
    assert "tests/research/factor" in lane.paths
    assert "packages/factor/onlyalpha-plugin-factors/tests" in lane.paths
    assert "tests/research/calculation/test_execution.py" in lane.paths
    assert "tests/architecture/test_research_factor_boundaries.py" in lane.paths
    source = Path("scripts/test_suite.py").read_text()
    assert '"research-factor-coverage"' in source
    assert "100 if name is OnlyTestLane.RESEARCH_FACTOR" in source


def test_research_sweep_lane_owns_composition_architecture_and_branch_coverage() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_SWEEP]
    assert lane.paths == (
        "tests/research/sweep",
        "tests/architecture/test_research_sweep_boundaries.py",
    )
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/research/sweep"' in source
    assert '"research-sweep-coverage"' in source
    assert "Research Sweep branch coverage must be at least 85%" in source


def test_research_evaluation_lane_owns_target_statistics_and_strict_coverage() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_EVALUATION]
    assert lane.paths == (
        "tests/research/evaluation",
        "packages/target/onlyalpha-plugin-targets/tests",
        "tests/architecture/test_research_evaluation_boundaries.py",
        "tests/research/factor/test_indicator_identity_regression.py",
    )
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/research/evaluation"' in source
    assert '"research-evaluation-coverage"' in source
    assert "OnlyTestLane.RESEARCH_EVALUATION" in source
    assert "Research Evaluation branch coverage must be at least 90%" in source
    assert "Research Evaluation line coverage must be at least 95%" in source


def test_research_result_lane_owns_composition_architecture_and_strict_coverage() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_RESULT]
    assert lane.paths == (
        "tests/research/result",
        "tests/architecture/test_research_result_boundaries.py",
    )
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/research/result"' in source
    assert '"research-result-coverage"' in source
    assert "Research Result branch coverage must be at least 90%" in source
    assert "Research Result line coverage must be at least 95%" in source


def test_research_artifact_lane_owns_portable_boundary_and_strict_coverage() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_ARTIFACT]
    assert lane.paths == (
        "tests/research/artifact",
        "tests/architecture/test_research_artifact_boundaries.py",
    )
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/research/artifact"' in source
    assert '"research-artifact-coverage"' in source
    assert "Research Artifact branch coverage must be at least 90%" in source
    assert "Research Artifact line coverage must be at least 95%" in source


def test_research_query_lane_owns_core_api_architecture_and_strict_coverage() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_QUERY]
    assert lane.paths == (
        "tests/research/query",
        "tests/architecture/test_research_query_boundaries.py",
        "packages/api/onlyalpha-api/tests",
    )
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/research/query"' in source
    assert '"packages/api/onlyalpha-api/src/onlyalpha_api"' in source
    assert '"research-query-coverage"' in source
    assert "Research Query branch coverage must be at least 90%" in source
    assert "Research Query line coverage must be at least 95%" in source


def test_research_command_lane_owns_application_http_and_architecture_contract() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_COMMAND]
    assert lane.paths == (
        "tests/research/command",
        "tests/architecture/test_research_command_boundaries.py",
        "packages/api/onlyalpha-api/tests",
    )
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/research/command"' in source
    assert '"research-command-coverage"' in source
    assert "Research Command branch coverage must be at least 85%" in source
    assert "Research Command line coverage must be at least 90%" in source


def test_research_runtime_lane_owns_product_orchestration_and_strict_coverage() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_RUNTIME]
    assert "tests/runtime/research" in lane.paths
    assert "tests/architecture/test_research_runtime_boundaries.py" in lane.paths
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/runtime/research"' in source
    assert '"research-runtime-coverage"' in source
    assert "Research Runtime branch coverage must be at least 90%" in source
    assert "Research Runtime line coverage must be at least 95%" in source


def test_research_specification_lane_owns_compiler_architecture_equivalence_and_full_coverage() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_SPECIFICATION]
    assert lane.paths == (
        "tests/research/specification",
        "tests/research/definition/test_resolution.py",
        "tests/architecture/test_research_specification_boundaries.py",
        "tests/runtime/research/test_product.py::test_specification_resolved_and_manual_workloads_have_full_runtime_equivalence",
    )
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/research/specification"' in source
    assert '"research-specification-coverage"' in source
    assert "Research Specification branch coverage must be 100%" in source
    assert "Research Specification line coverage must be 100%" in source


def test_research_run_and_postgres_lanes_separate_pure_domain_from_real_database() -> None:
    run = LANES[OnlyTestLane.RESEARCH_RUN]
    postgres = LANES[OnlyTestLane.RESEARCH_POSTGRES]
    source = Path("scripts/test_suite.py").read_text()
    assert run.expression == "not external"
    assert "tests/research/run" in run.paths
    assert postgres.expression == "postgres or architecture"
    assert postgres.workers == "0"
    assert "tests/research/postgres" in postgres.paths
    assert "Research Run branch coverage must be 100%" in source
    assert "Research Run line coverage must be 100%" in source


def test_research_execution_lane_owns_attempt_scheduler_worker_and_architecture() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_EXECUTION]
    source = Path("scripts/test_suite.py").read_text()
    assert lane.paths == (
        "tests/research/execution",
        "tests/architecture/test_research_execution_boundaries.py",
    )
    assert lane.expression == "not external"
    assert '"src/onlyalpha/research/execution"' in source
    assert '"research-execution-coverage"' in source
    assert "Research Execution branch coverage must be at least 85%" in source
    assert "Research Execution line coverage must be at least 95%" in source
