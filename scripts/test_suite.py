from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CANONICAL_DURATION_PATH = ROOT / "test-data" / "test-durations.json"


def workspace_test_paths(pyproject: Path = ROOT / "pyproject.toml") -> tuple[str, ...]:
    document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    try:
        configured = document["tool"]["pytest"]["ini_options"]["testpaths"]
    except (KeyError, TypeError) as exc:
        raise ValueError("pyproject.toml must define tool.pytest.ini_options.testpaths") from exc
    if (
        not isinstance(configured, list)
        or not configured
        or not all(isinstance(path, str) and path for path in configured)
    ):
        raise ValueError("tool.pytest.ini_options.testpaths must be a non-empty string array")
    paths = tuple(str(path) for path in configured)
    if len(paths) != len(set(paths)):
        raise ValueError("tool.pytest.ini_options.testpaths contains duplicate paths")
    return paths


WORKSPACE_TESTS = workspace_test_paths()


class OnlyTestLane(StrEnum):
    ARCHITECTURE = "architecture"
    PYTHON_CONTRACT = "python-contract"
    KERNEL = "kernel"
    STRATEGY = "strategy"
    CALCULATION = "calculation"
    RESEARCH_DEFINITION = "research-definition"
    RESEARCH_CALCULATION = "research-calculation"
    RESEARCH_FACTOR = "research-factor"
    RESEARCH_EVALUATION = "research-evaluation"
    RESEARCH_RESULT = "research-result"
    RESEARCH_ARTIFACT = "research-artifact"
    RESEARCH_QUERY = "research-query"
    RESEARCH_COMMAND = "research-command"
    RESEARCH_SPECIFICATION = "research-specification"
    RESEARCH_RUN = "research-run"
    RESEARCH_EXECUTION = "research-execution"
    RESEARCH_POSTGRES = "research-postgres"
    MARKET_DATA_CLICKHOUSE = "market-data-clickhouse"
    DATABASE_ACCEPTANCE = "database-acceptance"
    DATABASE = "database"
    RESEARCH_PRODUCT_CERTIFICATION = "research-product-certification"
    RESEARCH_RUNTIME = "research-runtime"
    RESEARCH_JOB = "research-job"
    RESEARCH_SWEEP = "research-sweep"
    RESEARCH_DATASET = "research-dataset"
    PRIVATE_ASSET_CONTRACT = "private-asset-contract"
    FAST = "fast"
    INTEGRATION = "integration"
    ASHARE = "ashare"
    RECOVERY = "recovery"
    SIM_RECOVERY = "sim-recovery"
    CORE_FULL = "core-full"
    EXHAUSTIVE = "exhaustive"
    RELEASE = "release"


class OnlyReleaseCheck(StrEnum):
    STATIC = "release-static"
    WEB_STATIC = "web-static"
    WEB_UNIT = "web-unit"
    WEB_BUILD = "web-build"
    WEB_E2E = "web-e2e"
    RUST_KERNEL = "rust-kernel"
    BUILD = "build"


COVERAGE_PARALLEL_LANES = frozenset({OnlyTestLane.KERNEL})


@dataclass(frozen=True, slots=True)
class Lane:
    paths: tuple[str, ...]
    expression: str
    workers: str
    dist: str
    durations: int = 20
    prefilter_marker: str | None = None
    timeout_seconds: int = 180


LANES = {
    OnlyTestLane.PYTHON_CONTRACT: Lane(
        (
            "packages/backend/python/algorithms/tests",
            "packages/backend/python/gateway_protocol/tests",
            "packages/backend/tests/transport/test_authoring_session_protocol.py",
            "packages/backend/tests/transport/test_trading_algorithm_session.py",
            "packages/backend/tests/transport/test_trading_algorithm_transport.py",
            "packages/backend/tests/transport/test_chart_algorithm_closure.py",
            "packages/backend/tests/transport/test_native_web_assets.py",
            "packages/backend/tests/transport/test_native_process_startup.py",
            "packages/backend/tests/workers/test_installed_trading_nodes.py",
            "packages/backend/tests/application/test_research_algorithm_execution.py",
        ),
        "not (external or postgres or clickhouse)",
        "0",
        "no",
        40,
        timeout_seconds=180,
    ),
    OnlyTestLane.DATABASE: Lane(
        (
            "packages/backend/tests/application/test_schema_postgres.py",
            "packages/backend/tests/application/test_command_postgres.py",
            "packages/backend/tests/application/test_private_factor_authoring_postgres.py",
            "packages/backend/tests/application/test_research_namespace_postgres.py",
            "packages/backend/tests/application/test_credential_postgres.py",
            "packages/backend/tests/application/test_deployment_postgres.py",
            "packages/backend/tests/application/test_integration_postgres.py",
            "packages/backend/tests/application/test_integration_commands_postgres.py",
            "packages/backend/tests/application/test_integration_draft_postgres.py",
            "packages/backend/tests/application/test_integration_publish_postgres.py",
            "packages/backend/tests/application/test_integration_secret_postgres.py",
            "packages/backend/tests/application/test_integration_authoring_postgres.py",
            "packages/backend/tests/application/test_integration_effect_postgres.py",
            "packages/backend/tests/application/test_watchlist_postgres.py",
            "packages/backend/tests/application/test_clickhouse_schema.py",
            "packages/backend/tests/application/test_runtime_registry_operator.py",
            "packages/backend/tests/application/test_backtest_evidence_operator.py",
            "packages/backend/tests/application/test_factor_proposals_postgres.py",
            "packages/backend/tests/application/test_factor_studies_postgres.py",
            "packages/backend/tests/application/test_private_strategy_authoring_postgres.py",
            "packages/backend/tests/application/test_workspace_postgres.py",
            "packages/backend/tests/application/test_runtime_installation_postgres.py",
            "packages/backend/tests/application/test_authoring_generation_postgres.py",
            "packages/backend/tests/application/test_research_input_admission_storage.py",
            "packages/backend/tests/application/test_market_storage_postgres_clickhouse.py",
            "packages/backend/tests/application/test_research_preparation_installation.py",
            "packages/backend/tests/application/test_research_algorithm_execution.py",
            "packages/backend/tests/application/test_native_market_source_application.py",
            "packages/backend/tests/transport/test_native_startup_storage.py",
            "packages/backend/tests/transport/test_native_integration_queries.py",
            "packages/backend/tests/transport/test_native_frozen_strategy.py",
            "packages/backend/tests/transport/test_native_node_authority.py",
            "packages/backend/tests/transport/test_native_qualification_policy.py",
            "packages/backend/tests/transport/test_native_strategy_projection.py",
        ),
        "postgres or clickhouse",
        "0",
        "no",
        40,
        timeout_seconds=900,
    ),
    OnlyTestLane.ARCHITECTURE: Lane(
        (
            "scripts/tests/test_dependency_audit_contract.py",
            "scripts/tests/test_test_topology_contract.py",
            "scripts/tests/test_current_ci_entrypoints.py",
            "scripts/tests/test_dev_verification_prepare.py",
            "scripts/tests/test_dev_verification_git_inputs.py",
            "scripts/tests/test_current_coverage_contract.py",
            "scripts/tests/test_domain_mutation.py",
            "scripts/tests/test_crate_layout_contract.py",
            "scripts/tests/test_import_owner_boundaries.py",
        ),
        "architecture",
        "0",
        "no",
    ),
    OnlyTestLane.KERNEL: Lane(
        (
            "tests/kernel",
            "tests/architecture/test_kernel_boundary.py",
            "tests/architecture/test_product_kernel_boundary.py",
        ),
        "unit or architecture",
        "0",
        "no",
    ),
    OnlyTestLane.STRATEGY: Lane(
        (
            "tests/strategy",
            "tests/architecture/test_strategy_authority.py",
            "tests/config/test_run_config.py",
        ),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.CALCULATION: Lane(
        (
            "tests/calculation",
            "tests/indicator",
            "packages/backend/python/algorithms/tests/test_codec.py",
            "packages/backend/python/algorithms/tests/test_type_declaration.py",
            "tests/plugin/test_calculation_plugin_discovery.py",
            "tests/plugin/test_entry_point_discovery.py",
            "tests/plugin/test_quant_asset_catalog.py",
            "tests/architecture/test_calculation_plugin_boundaries.py",
        ),
        "not external",
        "4",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_DEFINITION: Lane(
        (
            "tests/research/definition",
            "tests/architecture/test_research_definition_boundaries.py",
        ),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_CALCULATION: Lane(
        (
            "tests/research/calculation",
            "tests/calculation",
            "tests/architecture/test_research_calculation_boundaries.py",
            "tests/architecture/test_calculation_plugin_boundaries.py",
        ),
        "not external",
        "4",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_FACTOR: Lane(
        (
            "tests/research/factor",
            "tests/quant_assets/test_private_factor_native_execution.py",
            "tests/research/calculation/test_execution.py",
            (
                "tests/research/calculation/test_execution_evidence.py"
                "::test_execution_evidence_rejects_graph_binding_set_mismatch"
            ),
            "tests/architecture/test_research_factor_boundaries.py",
            "tests/architecture/test_calculation_plugin_boundaries.py",
            "tests/plugin/test_quant_asset_catalog.py",
        ),
        "not external",
        "4",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_EVALUATION: Lane(
        (
            "packages/backend/python/algorithms/tests",
            "packages/backend/tests/application/test_research_algorithm_execution.py",
            "packages/backend/tests/transport/test_authoring_session_protocol.py",
        ),
        "not (external or postgres or clickhouse)",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_RESULT: Lane(
        (
            "tests/research/result",
            "tests/architecture/test_research_result_boundaries.py",
        ),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_ARTIFACT: Lane(
        (
            "tests/research/artifact",
            "tests/architecture/test_research_artifact_boundaries.py",
        ),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_QUERY: Lane(
        (
            "tests/research/query",
            "tests/architecture/test_research_query_boundaries.py",
            "packages/backend/tests/transport",
        ),
        "not external and not postgres",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_COMMAND: Lane(
        (
            "tests/research/command",
            "tests/architecture/test_research_command_boundaries.py",
            "packages/backend/tests/transport",
        ),
        "not external and not postgres",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_SPECIFICATION: Lane(
        (
            "tests/research/specification",
            "tests/research/definition/test_resolution.py",
            "tests/architecture/test_research_specification_boundaries.py",
            "tests/runtime/research/test_product.py::test_specification_resolved_and_manual_workloads_have_full_runtime_equivalence",
        ),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_RUN: Lane(
        ("tests/research/run", "tests/architecture/test_research_run_boundaries.py"),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_EXECUTION: Lane(
        (
            "tests/research/execution",
            "tests/architecture/test_research_execution_boundaries.py",
        ),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_POSTGRES: Lane(
        (
            "tests/research/postgres",
            "tests/persistence",
            "tests/architecture/test_postgres_operational_authority.py",
            "packages/backend/tests/transport/test_native_integration_queries.py",
            "packages/backend/tests/transport/test_native_frozen_strategy.py",
            "packages/backend/tests/application",
            "tests/tools/test_chart_study_query_fixture.py",
        ),
        "postgres or architecture",
        "0",
        "no",
        40,
        timeout_seconds=600,
    ),
    OnlyTestLane.MARKET_DATA_CLICKHOUSE: Lane(
        ("tests/market_data_durable",),
        "clickhouse and external and requires_network and not database_acceptance",
        "0",
        "no",
        100,
        timeout_seconds=900,
    ),
    OnlyTestLane.DATABASE_ACCEPTANCE: Lane(
        ("tests/market_data_durable/test_real_database_acceptance.py",),
        "database_acceptance and postgres and clickhouse and external and requires_network",
        "0",
        "no",
        100,
        timeout_seconds=900,
    ),
    OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION: Lane(
        (
            "packages/backend/tests/application/test_strategy_research_evidence.py",
            "packages/backend/tests/application/test_manual_backtest_validation.py",
            "packages/backend/tests/application/test_strategy_freeze_commands.py",
        ),
        "postgres",
        "0",
        "no",
        40,
        timeout_seconds=900,
    ),
    OnlyTestLane.RESEARCH_RUNTIME: Lane(
        (
            "tests/runtime/research",
            "tests/runtime/factory/test_runtime_factory.py",
            "tests/engine/test_runtime_planning.py",
            "tests/engine/test_engine_wait.py",
            "tests/architecture/test_research_runtime_boundaries.py",
        ),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_JOB: Lane(
        (
            "tests/research/job",
            "tests/architecture/test_research_calculation_boundaries.py",
        ),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_SWEEP: Lane(
        (
            "tests/research/sweep",
            "tests/architecture/test_research_sweep_boundaries.py",
        ),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_DATASET: Lane(
        (
            "tests/research/dataset",
            "tests/cache",
            "tests/architecture/test_research_dataset_boundaries.py",
            "tests/architecture/test_historical_provider_boundaries.py",
            "plugs/onlyalpha-data-source-tushare/tests/test_provider.py",
            "plugs/onlyalpha-data-source-tushare/tests/test_historical.py",
        ),
        "not external",
        "4",
        "worksteal",
    ),
    OnlyTestLane.PRIVATE_ASSET_CONTRACT: Lane(
        (
            "packages/backend/python/algorithms/tests",
            "packages/backend/tests/transport/test_authoring_session_protocol.py",
            "packages/backend/tests/transport/test_trading_algorithm_session.py",
        ),
        "not (external or postgres or clickhouse)",
        "0",
        "no",
    ),
    OnlyTestLane.FAST: Lane(
        WORKSPACE_TESTS,
        "(unit or contract or architecture) and not (historical_git or recovery or sim_recovery or conformance or external or postgres or exhaustive or slow)",
        "8",
        "worksteal",
        timeout_seconds=300,
    ),
    OnlyTestLane.INTEGRATION: Lane(
        ("tests",),
        "(integration or scenario) and not (recovery or sim_recovery or conformance or external or exhaustive or slow)",
        "6",
        "worksteal",
        timeout_seconds=900,
    ),
    OnlyTestLane.ASHARE: Lane(
        WORKSPACE_TESTS,
        "conformance and not external and not exhaustive",
        "4",
        "worksteal",
        prefilter_marker="conformance",
    ),
    OnlyTestLane.RECOVERY: Lane(
        WORKSPACE_TESTS,
        "recovery and not external and not exhaustive",
        "8",
        "worksteal",
        100,
        "recovery",
        timeout_seconds=900,
    ),
    OnlyTestLane.SIM_RECOVERY: Lane(
        WORKSPACE_TESTS,
        "sim_recovery and not external and not exhaustive",
        "4",
        "worksteal",
        100,
        "sim_recovery",
        timeout_seconds=900,
    ),
    OnlyTestLane.CORE_FULL: Lane(
        WORKSPACE_TESTS,
        "not (historical_git or recovery or sim_recovery or conformance or external or postgres or clickhouse or requires_network or requires_tushare or requires_broker_account or exhaustive or slow)",
        "2",
        "loadfile",
        100,
    ),
    OnlyTestLane.EXHAUSTIVE: Lane(
        WORKSPACE_TESTS,
        "exhaustive and not external",
        "8",
        "worksteal",
        100,
        "exhaustive",
        timeout_seconds=900,
    ),
}

RELEASE_STATIC_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("uv", "run", "ruff", "check", "packages", "scripts"),
    ("uv", "run", "ruff", "format", "--check", "packages", "scripts"),
    ("uv", "run", "mypy"),
    (
        "python",
        "scripts/dev_verification.py",
        "run",
        "--",
        "python",
        "scripts/rust_kernel_check.py",
        "--package",
        "onlyalpha-broker",
        "--package",
        "onlyalpha-market-crypto",
        "--package",
        "onlyalpha-market-cn-ashare",
        "--package",
        "onlyalpha-data-source-tushare",
        "--package",
        "onlyalpha-data-source-binance",
    ),
    ("python", "scripts/rust_kernel_check.py", "--source-check"),
    ("uv", "run", "lint-imports"),
    ("uv", "run", "python", "scripts/version_sync.py", "check"),
)
BUILD_COMMAND = ("uv", "build", "--all-packages")
RELEASE_LANES = (
    OnlyTestLane.ARCHITECTURE,
    OnlyTestLane.PYTHON_CONTRACT,
    OnlyTestLane.PRIVATE_ASSET_CONTRACT,
    OnlyTestLane.RESEARCH_EVALUATION,
    OnlyTestLane.DATABASE,
    OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION,
)


def release_check_commands(check: OnlyReleaseCheck) -> tuple[tuple[str, ...], ...]:
    if check is OnlyReleaseCheck.RUST_KERNEL:
        return (("uv", "run", "python", "scripts/rust_kernel_check.py"),)
    if check is OnlyReleaseCheck.STATIC:
        return RELEASE_STATIC_COMMANDS
    if check is OnlyReleaseCheck.WEB_STATIC:
        return (("uv", "run", "python", "scripts/web_suite.py", "static"),)
    if check is OnlyReleaseCheck.WEB_UNIT:
        return (("uv", "run", "python", "scripts/web_suite.py", "unit"),)
    if check is OnlyReleaseCheck.WEB_BUILD:
        return (("uv", "run", "python", "scripts/web_suite.py", "build"),)
    if check is OnlyReleaseCheck.WEB_E2E:
        return (("uv", "run", "python", "scripts/web_suite.py", "e2e"),)
    return (BUILD_COMMAND,)


def execute_release_check(check: OnlyReleaseCheck) -> int:
    for command in release_check_commands(check):
        code = run(list(command))
        if code:
            return code
    return 0


def run(command: list[str], env: dict[str, str] | None = None) -> int:
    print("> " + subprocess.list2cmdline(command), flush=True)
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def selected_workers(
    lane: Lane,
    *,
    lane_name: OnlyTestLane,
    requested_workers: str | None,
    no_parallel: bool,
    coverage: bool,
) -> str:
    workers = "0" if no_parallel else (requested_workers or lane.workers)
    if coverage and requested_workers is None and not no_parallel:
        return "0"
    if coverage and requested_workers is not None and lane_name not in COVERAGE_PARALLEL_LANES:
        raise ValueError("parallel coverage is not proven safe for this lane")
    return workers


def release(args: argparse.Namespace) -> int:
    if (
        args.coverage
        or args.splits is not None
        or args.group is not None
        or args.collect_only
        or args.collection_path is not None
        or args.store_durations
        or args.clean_durations
    ):
        raise ValueError(
            "release requires complete current owners; lane measurement and shard options are not supported"
        )
    code = execute_release_check(OnlyReleaseCheck.STATIC)
    if code:
        return code
    for check in (OnlyReleaseCheck.RUST_KERNEL,):
        for command in release_check_commands(check):
            code = run(["python", "scripts/dev_verification.py", "run", "--", *command])
            if code:
                return code
    for lane in RELEASE_LANES:
        code = run(
            [
                "python",
                "scripts/dev_verification.py",
                "run",
                "--",
                "python",
                "scripts/test_suite.py",
                lane.value,
                "--no-parallel",
            ]
        )
        if code:
            return code
    for check in (OnlyReleaseCheck.WEB_STATIC, OnlyReleaseCheck.WEB_UNIT, OnlyReleaseCheck.WEB_BUILD):
        for command in release_check_commands(check):
            code = run(["python", "scripts/dev_verification.py", "run", "--", *command])
            if code:
                return code
    code = run(["bash", "deploy/run-web-e2e.sh"])
    if code:
        return code
    return run(list(BUILD_COMMAND))


def prepare_native_test_artifacts(name: OnlyTestLane) -> None:
    """Compile this owner's actual fixtures before starting its test-case budgets."""
    if name is OnlyTestLane.DATABASE:
        from packages.backend.tests.application.conftest import build_native_probe
        from packages.backend.tests.transport.conftest import build_integration_http_probe
        from scripts.native_http_contract import native_executable

        build_native_probe(release=False)
        build_native_probe(release=True)
        native_executable(release=False)
        native_executable(release=True)
        build_integration_http_probe()
    elif name is OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION:
        from packages.backend.tests.application.conftest import build_native_probe
        from packages.backend.tests.application.test_strategy_research_evidence import (
            _build_strategy_evidence_owner_binary,
        )
        from scripts.native_http_contract import native_executable

        build_native_probe(release=False)
        build_native_probe(release=True)
        native_executable(release=True)
        _build_strategy_evidence_owner_binary(release=False, build_timeout=None)
        _build_strategy_evidence_owner_binary(release=True, build_timeout=None)
        _build_strategy_evidence_owner_binary(release=True, build_timeout=None, target_name="backtest_owner_probe")
    elif name in {OnlyTestLane.PRIVATE_ASSET_CONTRACT, OnlyTestLane.PYTHON_CONTRACT}:
        from packages.backend.tests.workers.test_installed_trading_nodes import build_installed_trading_binary

        if name is OnlyTestLane.PYTHON_CONTRACT:
            from packages.backend.tests.transport.conftest import build_integration_http_probe
            from scripts.native_http_contract import native_executable

            # These actual offline consumers keep their original child/build
            # budgets; first Rust compilation precedes pytest's scenario timers.
            native_executable(release=True)
            build_integration_http_probe()
        # The Private Asset job also invokes this same installed-node owner next.
        build_installed_trading_binary(release=True, build_timeout=None)


def execute(name: OnlyTestLane, args: argparse.Namespace) -> int:
    lane = LANES[name]
    if args.coverage and name in {
        OnlyTestLane.RESEARCH_EVALUATION,
        OnlyTestLane.PRIVATE_ASSET_CONTRACT,
        OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION,
        OnlyTestLane.DATABASE,
        OnlyTestLane.PYTHON_CONTRACT,
    }:
        raise ValueError(
            "the current native owner has no admitted Python coverage measurement; Rust coverage must not be reported by pytest"
        )
    if args.collect_only and (args.splits is not None or args.coverage):
        raise ValueError("collection proof requires the unsplit lane without coverage")
    if (args.collection_path is not None) != args.collect_only:
        raise ValueError("--collect-only requires exactly one --collection-path")
    if args.group is not None and args.splits is None:
        print("--group requires --splits", file=sys.stderr)
        return 2
    if args.splits is not None and args.splits < 2:
        print("--splits must be at least 2", file=sys.stderr)
        return 2
    if args.splits is not None and (args.group is None or not 1 <= args.group <= args.splits):
        print("--group must be between 1 and --splits", file=sys.stderr)
        return 2
    if args.store_durations and args.splits is not None:
        print("duration authority cannot be updated by a shard", file=sys.stderr)
        return 2
    if args.clean_durations and args.splits is not None:
        print("duration data cannot be cleaned by a shard", file=sys.stderr)
        return 2
    try:
        workers = selected_workers(
            lane,
            lane_name=name,
            requested_workers=args.workers,
            no_parallel=args.no_parallel,
            coverage=args.coverage,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    dist = args.dist or lane.dist
    if workers != "0" and dist == "no":
        dist = "worksteal"
    command = [
        "uv",
        "run",
        "python",
        "-m",
        "pytest",
        "-c",
        str(ROOT / "pyproject.toml"),
        *lane.paths,
        "--import-mode=importlib",
        "-q",
        "-m",
        lane.expression,
        f"--durations={args.durations or lane.durations}",
        f"--timeout={lane.timeout_seconds}",
        "-p",
        "scripts.pytest_layering",
        "-p",
        "scripts.pytest_metrics",
    ]
    if args.collect_only:
        command.extend(["--collect-only", "--onlyalpha-collection-path", str(args.collection_path)])
    if lane.prefilter_marker is not None:
        command.extend(
            [
                "-p",
                "scripts.pytest_marker_prefilter",
                "--onlyalpha-prefilter-marker",
                lane.prefilter_marker,
            ]
        )
    if args.coverage:
        coverage_sources = {
            OnlyTestLane.RESEARCH_DEFINITION: ("src/onlyalpha/research/definition",),
            OnlyTestLane.RESEARCH_SPECIFICATION: ("src/onlyalpha/research/specification",),
            OnlyTestLane.RESEARCH_RUN: ("src/onlyalpha/research/run",),
            OnlyTestLane.RESEARCH_EXECUTION: ("src/onlyalpha/research/execution",),
            OnlyTestLane.RESEARCH_POSTGRES: ("src/onlyalpha/persistence/postgres",),
            OnlyTestLane.RESEARCH_RUNTIME: (
                "src/onlyalpha/runtime/research",
                "onlyalpha.runtime.product",
            ),
            OnlyTestLane.RESEARCH_QUERY: ("src/onlyalpha/research/query",),
            OnlyTestLane.RESEARCH_COMMAND: ("src/onlyalpha/research/command",),
            OnlyTestLane.RESEARCH_ARTIFACT: ("src/onlyalpha/research/artifact",),
            OnlyTestLane.RESEARCH_RESULT: ("src/onlyalpha/research/result",),
            OnlyTestLane.RESEARCH_EVALUATION: (
                "src/onlyalpha/research/evaluation",
                "onlyalpha_backend_algorithms.targets",
            ),
            OnlyTestLane.RESEARCH_SWEEP: ("src/onlyalpha/research/sweep",),
            OnlyTestLane.RESEARCH_FACTOR: (
                "onlyalpha.research.calculation.execution",
                "onlyalpha_test_factor_provider",
            ),
            OnlyTestLane.RESEARCH_JOB: ("src/onlyalpha/research/job",),
            OnlyTestLane.RESEARCH_CALCULATION: ("src/onlyalpha/research/calculation",),
            OnlyTestLane.CALCULATION: ("onlyalpha.algorithm",),
            OnlyTestLane.RESEARCH_DATASET: ("src/onlyalpha/research/dataset",),
        }.get(name, ("src/onlyalpha",))
        coverage_output = (
            "research-definition-coverage"
            if name is OnlyTestLane.RESEARCH_DEFINITION
            else "research-specification-coverage"
            if name is OnlyTestLane.RESEARCH_SPECIFICATION
            else "research-run-coverage"
            if name is OnlyTestLane.RESEARCH_RUN
            else "research-execution-coverage"
            if name is OnlyTestLane.RESEARCH_EXECUTION
            else "research-postgres-coverage"
            if name is OnlyTestLane.RESEARCH_POSTGRES
            else "research-runtime-coverage"
            if name is OnlyTestLane.RESEARCH_RUNTIME
            else "research-query-coverage"
            if name is OnlyTestLane.RESEARCH_QUERY
            else "research-command-coverage"
            if name is OnlyTestLane.RESEARCH_COMMAND
            else "research-artifact-coverage"
            if name is OnlyTestLane.RESEARCH_ARTIFACT
            else "research-result-coverage"
            if name is OnlyTestLane.RESEARCH_RESULT
            else "research-evaluation-coverage"
            if name is OnlyTestLane.RESEARCH_EVALUATION
            else "research-sweep-coverage"
            if name is OnlyTestLane.RESEARCH_SWEEP
            else "research-factor-coverage"
            if name is OnlyTestLane.RESEARCH_FACTOR
            else "research-job-coverage"
            if name is OnlyTestLane.RESEARCH_JOB
            else "research-calculation-coverage"
            if name is OnlyTestLane.RESEARCH_CALCULATION
            else "calculation-coverage"
            if name is OnlyTestLane.CALCULATION
            else "research-dataset-coverage"
            if name is OnlyTestLane.RESEARCH_DATASET
            else "coverage"
        )
        command.extend(
            [
                *(f"--cov={source}" for source in coverage_sources),
                "--cov-branch",
                "--cov-report=",
                f"--cov-report=json:test-results/coverage/{coverage_output}.json",
                f"--cov-report=xml:test-results/coverage/{coverage_output}.xml",
                f"--cov-fail-under={100 if name is OnlyTestLane.RESEARCH_FACTOR else 100 if name in (OnlyTestLane.RESEARCH_SPECIFICATION, OnlyTestLane.RESEARCH_RUN) else 95 if name in (OnlyTestLane.RESEARCH_EXECUTION, OnlyTestLane.RESEARCH_RUNTIME, OnlyTestLane.RESEARCH_QUERY, OnlyTestLane.RESEARCH_EVALUATION, OnlyTestLane.RESEARCH_RESULT, OnlyTestLane.RESEARCH_ARTIFACT) else 90 if name in (OnlyTestLane.RESEARCH_COMMAND, OnlyTestLane.RESEARCH_SWEEP) else 82}",
            ]
        )
    if workers != "0":
        command.extend(["-n", workers, "--dist", dist])
    durations_path = Path(args.durations_path) if args.durations_path else CANONICAL_DURATION_PATH
    if args.store_durations or args.clean_durations:
        if not durations_path.is_absolute():
            durations_path = ROOT / durations_path
        durations_path.parent.mkdir(parents=True, exist_ok=True)
    if args.splits is not None:
        command.extend(
            [
                "--splits",
                str(args.splits),
                "--group",
                str(args.group),
                "--splitting-algorithm",
                args.splitting_algorithm,
                "--durations-path",
                str(durations_path),
            ]
        )
    if args.store_durations or args.clean_durations:
        command.extend(["--durations-path", str(durations_path)])
    if args.store_durations:
        command.append("--store-durations")
    if args.clean_durations:
        command.append("--clean-durations")
    metric_path = (
        Path(args.metrics_path)
        if args.metrics_path is not None
        else ROOT / "test-results" / "metrics" / f"{name.value}{'-collection' if args.collect_only else ''}.json"
    )
    if not metric_path.is_absolute():
        metric_path = ROOT / metric_path
    env = os.environ.copy()
    env.update(
        {
            "ONLYALPHA_TEST_LANE": name.value,
            "ONLYALPHA_TEST_METRICS": str(metric_path),
            "ONLYALPHA_TEST_WORKERS": workers,
            "ONLYALPHA_TEST_DIST": dist if workers != "0" else "no",
        }
    )
    if not args.collect_only:
        prepare_native_test_artifacts(name)
    code = run(command, env)
    if args.coverage:
        coverage_path = (
            ROOT
            / "test-results"
            / "coverage"
            / (
                "research-specification-coverage.json"
                if name is OnlyTestLane.RESEARCH_SPECIFICATION
                else "research-definition-coverage.json"
                if name is OnlyTestLane.RESEARCH_DEFINITION
                else "research-run-coverage.json"
                if name is OnlyTestLane.RESEARCH_RUN
                else "research-execution-coverage.json"
                if name is OnlyTestLane.RESEARCH_EXECUTION
                else "research-postgres-coverage.json"
                if name is OnlyTestLane.RESEARCH_POSTGRES
                else "research-runtime-coverage.json"
                if name is OnlyTestLane.RESEARCH_RUNTIME
                else "research-query-coverage.json"
                if name is OnlyTestLane.RESEARCH_QUERY
                else "research-command-coverage.json"
                if name is OnlyTestLane.RESEARCH_COMMAND
                else "research-artifact-coverage.json"
                if name is OnlyTestLane.RESEARCH_ARTIFACT
                else "research-result-coverage.json"
                if name is OnlyTestLane.RESEARCH_RESULT
                else "calculation-coverage.json"
                if name is OnlyTestLane.CALCULATION
                else "research-evaluation-coverage.json"
                if name is OnlyTestLane.RESEARCH_EVALUATION
                else "research-sweep-coverage.json"
                if name is OnlyTestLane.RESEARCH_SWEEP
                else "research-factor-coverage.json"
                if name is OnlyTestLane.RESEARCH_FACTOR
                else "research-job-coverage.json"
                if name is OnlyTestLane.RESEARCH_JOB
                else "research-calculation-coverage.json"
                if name is OnlyTestLane.RESEARCH_CALCULATION
                else "research-dataset-coverage.json"
                if name is OnlyTestLane.RESEARCH_DATASET
                else "coverage.json"
            )
        )
        if coverage_path.is_file():
            totals = json.loads(coverage_path.read_text(encoding="utf-8"))["totals"]
            line_rate = 100 * totals["covered_lines"] / totals["num_statements"]
            branch_rate = 100 * totals["covered_branches"] / totals["num_branches"]
            print(f"Coverage baseline: lines={line_rate:.2f}% branches={branch_rate:.2f}%")
            if name is OnlyTestLane.RESEARCH_SPECIFICATION and branch_rate < 100:
                print("Research Specification branch coverage must be 100%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_SPECIFICATION and line_rate < 100:
                print("Research Specification line coverage must be 100%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_RUN and branch_rate < 100:
                print("Research Run branch coverage must be 100%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_RUN and line_rate < 100:
                print("Research Run line coverage must be 100%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_EXECUTION and branch_rate < 85:
                print("Research Execution branch coverage must be at least 85%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_EXECUTION and line_rate < 95:
                print("Research Execution line coverage must be at least 95%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_DATASET and branch_rate < 70:
                print("Research Dataset branch coverage must be at least 70%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_SWEEP and branch_rate < 85:
                print("Research Sweep branch coverage must be at least 85%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_EVALUATION and branch_rate < 90:
                print("Research Evaluation branch coverage must be at least 90%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_EVALUATION and line_rate < 95:
                print("Research Evaluation line coverage must be at least 95%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_RESULT and branch_rate < 90:
                print("Research Result branch coverage must be at least 90%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_RESULT and line_rate < 95:
                print("Research Result line coverage must be at least 95%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_ARTIFACT and branch_rate < 90:
                print("Research Artifact branch coverage must be at least 90%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_ARTIFACT and line_rate < 95:
                print("Research Artifact line coverage must be at least 95%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_QUERY and branch_rate < 90:
                print("Research Query branch coverage must be at least 90%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_QUERY and line_rate < 95:
                print("Research Query line coverage must be at least 95%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_COMMAND and branch_rate < 85:
                print("Research Command branch coverage must be at least 85%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_COMMAND and line_rate < 90:
                print("Research Command line coverage must be at least 90%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_RUNTIME and branch_rate < 90:
                print("Research Runtime branch coverage must be at least 90%", file=sys.stderr)
                code = 1
            if name is OnlyTestLane.RESEARCH_RUNTIME and line_rate < 95:
                print("Research Runtime line coverage must be at least 95%", file=sys.stderr)
                code = 1
    if metric_path.is_file():
        metrics = json.loads(metric_path.read_text(encoding="utf-8"))
        print(f"Lane {name.value}: {metrics['collected']} collected in {metrics['total_seconds']:.2f}s")
        if metrics["collected"] == 0 and code == 0:
            code = 5
    else:
        print(f"Lane {name.value}: metrics were not produced", file=sys.stderr)
        if code == 0:
            code = 2
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "lane", choices=[lane.value for lane in OnlyTestLane] + [check.value for check in OnlyReleaseCheck]
    )
    parser.add_argument("--workers")
    parser.add_argument("--dist", choices=("load", "loadscope", "loadfile", "worksteal"))
    parser.add_argument("--durations", type=int)
    parser.add_argument("--splits", type=int)
    parser.add_argument("--group", type=int)
    parser.add_argument(
        "--splitting-algorithm",
        choices=("duration_based_chunks", "least_duration"),
        default="least_duration",
    )
    parser.add_argument("--durations-path", type=Path)
    parser.add_argument("--store-durations", action="store_true")
    parser.add_argument("--clean-durations", action="store_true")
    parser.add_argument("--metrics-path", type=Path)
    parser.add_argument("--no-parallel", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--collection-path", type=Path)
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="collect branch coverage once for this lane; serial by default, explicit --workers only for proven lanes",
    )
    args = parser.parse_args()
    if args.lane in {check.value for check in OnlyReleaseCheck}:
        return execute_release_check(OnlyReleaseCheck(args.lane))
    lane = OnlyTestLane(args.lane)
    return release(args) if lane is OnlyTestLane.RELEASE else execute(lane, args)


if __name__ == "__main__":
    raise SystemExit(main())
