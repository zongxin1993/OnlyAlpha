from __future__ import annotations

import json
import os
import select
import shlex
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

import scripts.test_suite as test_suite
from scripts.pytest_layering import CONCERN_MARKERS, LAYER_MARKERS, path_concerns, path_layer
from scripts.test_suite import LANES, OnlyTestLane, selected_workers

pytestmark = pytest.mark.architecture


def test_research_http_lanes_are_db_free_and_postgres_lane_owns_real_http_flow() -> None:
    path = "packages/onlyalpha-http-server/tests/test_integration_postgres_api.py"
    for name in (OnlyTestLane.RESEARCH_COMMAND, OnlyTestLane.RESEARCH_QUERY):
        lane = LANES[name]
        assert lane.expression == "not external and not postgres"
        assert "packages/onlyalpha-http-server/tests" in lane.paths
    postgres = LANES[OnlyTestLane.RESEARCH_POSTGRES]
    assert postgres.paths.count(path) == 1
    assert postgres.expression == "postgres or architecture"
    assert (postgres.workers, postgres.dist, postgres.timeout_seconds) == ("0", "no", 600)


def test_database_compose_runs_independent_database_lanes_before_cross_database_acceptance() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/quality.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["database-compose"]
    assert job["timeout-minutes"] == 35
    steps = job["steps"]
    commands = [step["run"] for step in steps if "run" in step]
    prefix = "docker compose -f deploy/docker-compose.dev.yml"
    assert f"{prefix} config --quiet" in commands
    assert f"{prefix} up -d --build --wait" in commands
    orchestration = [command for command in commands if f"{prefix} --profile test run --rm test" in command]
    assert len(orchestration) == 1
    command = orchestration[0]
    assert "bash -c" in command
    assert "bash -lc" not in command
    assert "set -euo pipefail" in command
    assert command.count("python scripts/embed_build_provenance.py") == 1
    postgres = "python scripts/test_suite.py research-postgres &"
    clickhouse = "python scripts/test_suite.py market-data-clickhouse &"
    acceptance = "python scripts/test_suite.py database-acceptance"
    for lane in (postgres, clickhouse, acceptance):
        assert command.count(lane) == 1
    assert command.index(postgres) < command.index('wait "$postgres_pid"')
    assert command.index(clickhouse) < command.index('wait "$postgres_pid"')
    assert command.index('wait "$postgres_pid" || postgres_status=$?') < command.index(acceptance)
    assert command.index('wait "$clickhouse_pid" || clickhouse_status=$?') < command.index(acceptance)
    assert command.index('test "$postgres_status" -eq 0') < command.index(acceptance)
    assert command.index('test "$clickhouse_status" -eq 0') < command.index(acceptance)
    cleanup = next(step for step in steps if step.get("name") == "Remove the test stack")
    assert cleanup["if"] == "always()"
    assert cleanup["run"] == f"{prefix} down -v"


@pytest.mark.parametrize(("postgres_status", "clickhouse_status"), ((0, 0), (7, 0), (0, 9), (7, 9)))
def test_database_compose_waits_for_both_lanes_and_fails_closed(
    tmp_path: Path, postgres_status: int, clickhouse_status: int
) -> None:
    workflow = yaml.safe_load(Path(".github/workflows/quality.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["database-compose"]["steps"]
    command = next(step["run"] for step in steps if "bash -c" in step.get("run", ""))
    tokens = shlex.split(command.replace("\\\n", ""))
    shell_arguments = tokens[tokens.index("bash") + 1 :]
    assert shell_arguments[0] == "-c"
    fake_python = tmp_path / "python"
    fake_python.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "name = sys.argv[-1]\n"
        "with open(os.environ['LANE_LOG'], 'a') as log:\n"
        "    log.write(name + '\\n')\n"
        "if name in ('research-postgres', 'market-data-clickhouse'):\n"
        "    key = 'POSTGRES' if name == 'research-postgres' else 'CLICKHOUSE'\n"
        "    os.write(int(os.environ['EVENT_FD']), key[0].encode())\n"
        "    os.read(int(os.environ[key + '_RELEASE_FD']), 1)\n"
        "    os.write(int(os.environ['EVENT_FD']), key[0].lower().encode())\n"
        "    sys.exit(int(os.environ[key + '_STATUS']))\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    events_read, events_write = os.pipe()
    postgres_read, postgres_write = os.pipe()
    clickhouse_read, clickhouse_write = os.pipe()
    log = tmp_path / "lanes.log"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "LANE_LOG": str(log),
        "EVENT_FD": str(events_write),
        "POSTGRES_RELEASE_FD": str(postgres_read),
        "CLICKHOUSE_RELEASE_FD": str(clickhouse_read),
        "POSTGRES_STATUS": str(postgres_status),
        "CLICKHOUSE_STATUS": str(clickhouse_status),
    }
    process = subprocess.Popen(
        ["bash", *shell_arguments], env=env, pass_fds=(events_write, postgres_read, clickhouse_read)
    )

    def event() -> bytes:
        assert select.select([events_read], [], [], 20)[0], "database lane barrier was not reached"
        return os.read(events_read, 1)

    try:
        assert {event(), event()} == {b"P", b"C"}
        os.write(postgres_write, b"1")
        assert event() == b"p"
        assert process.poll() is None
        assert "database-acceptance" not in log.read_text(encoding="utf-8")
        os.write(clickhouse_write, b"1")
        assert event() == b"c"
        status = process.wait(timeout=20)
        assert (status == 0) == (postgres_status == clickhouse_status == 0)
        lanes = log.read_text(encoding="utf-8").splitlines()
        assert lanes[0] == "scripts/embed_build_provenance.py"
        assert set(lanes[1:3]) == {"research-postgres", "market-data-clickhouse"}
        assert lanes[3:] == (["database-acceptance"] if status == 0 else [])
    finally:
        for descriptor in (events_read, events_write, postgres_read, postgres_write, clickhouse_read, clickhouse_write):
            os.close(descriptor)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=20)


def test_layer_and_concern_taxonomies_are_orthogonal() -> None:
    assert LAYER_MARKERS == {"unit", "contract", "architecture", "integration", "scenario"}
    assert CONCERN_MARKERS == {
        "recovery",
        "sim_recovery",
        "conformance",
        "external",
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
    assert all(concern in core for concern in ("recovery", "conformance", "exhaustive", "postgres", "clickhouse"))
    assert "postgres" in LANES[OnlyTestLane.FAST].expression
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


def test_coverage_is_serial_by_default_but_explicit_workers_enable_proven_xdist() -> None:
    lane = LANES[OnlyTestLane.KERNEL]
    assert (
        selected_workers(lane, lane_name=OnlyTestLane.KERNEL, requested_workers=None, no_parallel=False, coverage=True)
        == "0"
    )
    assert (
        selected_workers(lane, lane_name=OnlyTestLane.KERNEL, requested_workers="2", no_parallel=False, coverage=True)
        == "2"
    )
    assert (
        selected_workers(lane, lane_name=OnlyTestLane.KERNEL, requested_workers="2", no_parallel=True, coverage=True)
        == "0"
    )
    with pytest.raises(ValueError, match="not proven safe"):
        selected_workers(
            LANES[OnlyTestLane.CALCULATION],
            lane_name=OnlyTestLane.CALCULATION,
            requested_workers="2",
            no_parallel=False,
            coverage=True,
        )


def test_proven_parallel_coverage_reaches_the_pytest_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], env: dict[str, str] | None = None) -> int:
        assert env is not None
        captured["command"] = command
        captured["env"] = env
        Path(env["ONLYALPHA_TEST_METRICS"]).parent.mkdir(parents=True, exist_ok=True)
        Path(env["ONLYALPHA_TEST_METRICS"]).write_text(
            json.dumps({"collected": 1, "total_seconds": 0.0}), encoding="utf-8"
        )
        return 0

    monkeypatch.setattr(test_suite, "ROOT", tmp_path)
    monkeypatch.setattr(test_suite, "run", fake_run)
    args = Namespace(
        group=None,
        splits=None,
        store_durations=False,
        clean_durations=False,
        workers="2",
        no_parallel=False,
        coverage=True,
        dist=None,
        durations=None,
        durations_path=None,
        splitting_algorithm="least_duration",
        metrics_path=None,
    )

    assert test_suite.execute(OnlyTestLane.KERNEL, args) == 0
    command = captured["command"]
    assert isinstance(command, list)
    assert "-n" in command
    assert command[command.index("-n") + 1] == "2"
    assert command[command.index("--dist") + 1] == "worksteal"


def test_kernel_lane_owns_lifecycle_host_and_product_boundary() -> None:
    lane = LANES[OnlyTestLane.KERNEL]
    assert lane.paths == (
        "tests/kernel",
        "tests/architecture/test_kernel_boundary.py",
        "tests/architecture/test_product_kernel_boundary.py",
    )
    assert lane.expression == "unit or architecture"
    assert lane.workers == "0"
    assert lane.dist == "no"


@pytest.mark.parametrize(("store", "clean"), ((True, False), (False, True), (True, True)))
@pytest.mark.parametrize("absolute", (False, True))
def test_duration_output_parent_is_prepared_before_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: bool, clean: bool, absolute: bool
) -> None:
    output = tmp_path / "test-results/topology/generated.json"
    supplied = output if absolute else output.relative_to(tmp_path)
    assert not output.parent.exists()

    def fake_run(command: list[str], env: dict[str, str] | None = None) -> int:
        assert output.parent.is_dir()
        assert command[command.index("--durations-path") + 1] == str(output)
        assert ("--store-durations" in command) is store
        assert ("--clean-durations" in command) is clean
        assert env is not None
        metrics = Path(env["ONLYALPHA_TEST_METRICS"])
        metrics.parent.mkdir(parents=True, exist_ok=True)
        metrics.write_text(json.dumps({"collected": 1, "total_seconds": 0.0}))
        return 0

    monkeypatch.setattr(test_suite, "ROOT", tmp_path)
    monkeypatch.setattr(test_suite, "run", fake_run)
    args = Namespace(
        group=None,
        splits=None,
        store_durations=store,
        clean_durations=clean,
        workers="0",
        no_parallel=False,
        coverage=False,
        dist=None,
        durations=None,
        durations_path=str(supplied),
        splitting_algorithm="least_duration",
        metrics_path=None,
    )
    assert test_suite.execute(OnlyTestLane.RESEARCH_EVALUATION, args) == 0
    assert not output.exists()


@pytest.mark.parametrize("existing", (False, True))
def test_duration_shard_input_is_read_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, existing: bool) -> None:
    input_path = tmp_path / "test-data/test-durations.json"
    before = b'{"test_node": 1.0}\n'
    if existing:
        input_path.parent.mkdir()
        input_path.write_bytes(before)

    def fake_run(command: list[str], env: dict[str, str] | None = None) -> int:
        assert "--store-durations" not in command and "--clean-durations" not in command
        assert Path(command[command.index("--durations-path") + 1]) == input_path
        assert command[command.index("--splits") + 1] == "4"
        assert command[command.index("--group") + 1] == "1"
        if existing:
            assert input_path.read_bytes() == before
        else:
            assert not input_path.parent.exists()
        assert env is not None
        metrics = Path(env["ONLYALPHA_TEST_METRICS"])
        metrics.parent.mkdir(parents=True, exist_ok=True)
        metrics.write_text(json.dumps({"collected": 1, "total_seconds": 0.0}))
        return 0

    monkeypatch.setattr(test_suite, "ROOT", tmp_path)
    monkeypatch.setattr(test_suite, "run", fake_run)
    args = Namespace(
        group=1,
        splits=4,
        store_durations=False,
        clean_durations=False,
        workers="0",
        no_parallel=False,
        coverage=False,
        dist=None,
        durations=None,
        durations_path=str(input_path),
        splitting_algorithm="least_duration",
        metrics_path=None,
    )
    assert test_suite.execute(OnlyTestLane.RESEARCH_EVALUATION, args) == 0
    if existing:
        assert input_path.read_bytes() == before
    else:
        assert not input_path.parent.exists()


def test_normal_ci_directly_runs_the_canonical_architecture_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "- run: uv run python scripts/test_suite.py architecture" in workflow
    assert "ARCHITECTURE_RESULT: ${{ needs.architecture.result }}" in workflow


def test_ci_shards_only_an_already_selected_canonical_lane_and_reads_duration_authority() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "research-evaluation-shards:" in workflow
    assert "--splits 4" in workflow
    assert "--splitting-algorithm least_duration" in workflow
    assert "--durations-path test-data/test-durations.json" in workflow
    assert "--store-durations" not in workflow
    assert "research-evaluation-shard-gate:" in workflow
    assert "--validate-shards" in workflow


def test_public_ci_runs_and_requires_private_asset_contract_conformance() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "uv run python scripts/test_suite.py private-asset-contract" in workflow
    assert "PRIVATE_ASSET_CONTRACT_RESULT: ${{ needs.private-asset-contract.result }}" in workflow


def test_research_job_lane_owns_application_contract_and_architecture_gate() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_JOB]
    assert lane.paths == (
        "tests/research/job",
        "tests/architecture/test_research_calculation_boundaries.py",
    )
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/research/job"' in source
    assert '"research-job-coverage"' in source


def test_agent_orchestrator_lane_mechanically_owns_package_and_shared_contract_tests() -> None:
    lane = LANES[OnlyTestLane.AGENT_ORCHESTRATOR]
    assert lane.paths == (
        "packages/onlyalpha-agent-orchestrator/tests",
        "tests/research/agent/test_identity_and_workflow.py",
        "tests/architecture/test_agent_orchestration_boundaries.py",
    )
    assert lane.expression == "not external"


def test_research_factor_lane_owns_semantics_execution_architecture_and_full_coverage() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_FACTOR]
    assert "tests/research/factor" in lane.paths
    assert "tests/quant_assets/test_private_factor_native_execution.py" in lane.paths
    assert "plugs/onlyalpha-plugin-operators/tests" in lane.paths
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
        "plugs/onlyalpha-plugin-targets/tests",
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
        "packages/onlyalpha-http-server/tests",
    )
    source = Path("scripts/test_suite.py").read_text()
    assert '"src/onlyalpha/research/query"' in source
    assert '"packages/onlyalpha-http-server/src/onlyalpha_http_server"' in source
    assert '"research-query-coverage"' in source
    assert "Research Query branch coverage must be at least 90%" in source
    assert "Research Query line coverage must be at least 95%" in source


def test_research_command_lane_owns_application_http_and_architecture_contract() -> None:
    lane = LANES[OnlyTestLane.RESEARCH_COMMAND]
    assert lane.paths == (
        "tests/research/command",
        "tests/architecture/test_research_command_boundaries.py",
        "packages/onlyalpha-http-server/tests",
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
    assert "tests/persistence" in postgres.paths
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
