from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import pytest_metrics, test_suite, verify
from scripts.test_topology import LaneMetrics, validate_shards

pytestmark = pytest.mark.architecture


def metric(nodes, *, commit="abc", collected=None, lane="research-evaluation"):
    return LaneMetrics(
        lane,
        len(nodes) if collected is None else collected,
        1.0,
        2,
        "worksteal",
        commit,
        "test",
        {node: 1.0 for node in nodes},
    )


@pytest.mark.parametrize(
    "nodes,shards,expected",
    [
        ({"a", "b"}, (metric(["a"]), metric(["b"])), True),
        ({"a", "b"}, (metric(["a"]), metric(["a", "b"])), False),
        ({"a", "b"}, (metric(["a"]),), False),
        ({"a"}, (metric(["a", "b"]),), False),
        (set(), (), False),
        ({"a"}, (metric(["a"]), metric([])), False),
        ({"a"}, (metric(["a"], collected=2),), False),
        ({"a"}, (metric(["a"], commit="old"),), False),
        ({"a", "b"}, (metric(["a"]), metric(["b"], lane="other")), False),
    ],
)
def test_current_shard_proof_requires_complete_disjoint_nonempty_exact_commit(nodes, shards, expected):
    assert validate_shards(shards, nodes, expected_commit="abc")["complete"] is expected


@pytest.mark.parametrize(
    "collect_only,exitstatus,nodes,valid",
    [
        (True, 0, ["a", "b"], True),
        (False, 0, ["a"], False),
        (True, 1, ["a"], False),
        (True, 0, [], False),
        (True, 0, ["a", "a"], False),
    ],
)
def test_collection_manifest_only_records_successful_nonempty_unique_collection(
    tmp_path, monkeypatch, collect_only, exitstatus, nodes, valid
):
    target = tmp_path / "nested" / "collection.json"
    config = SimpleNamespace(getoption=lambda name: target, option=SimpleNamespace(collectonly=collect_only))
    session = SimpleNamespace(config=config, items=[SimpleNamespace(nodeid=node) for node in nodes])
    monkeypatch.delenv("ONLYALPHA_TEST_METRICS", raising=False)
    monkeypatch.delenv("ONLYALPHA_TEST_LANE", raising=False)
    if valid:
        pytest_metrics.pytest_sessionfinish(session, exitstatus)
        assert json.loads(target.read_text()) == sorted(nodes)
    else:
        with pytest.raises(pytest.UsageError):
            pytest_metrics.pytest_sessionfinish(session, exitstatus)
        assert not target.exists()


@pytest.mark.parametrize(
    "lane",
    [
        test_suite.OnlyTestLane.RESEARCH_EVALUATION,
        test_suite.OnlyTestLane.PRIVATE_ASSET_CONTRACT,
        test_suite.OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION,
        test_suite.OnlyTestLane.DATABASE,
    ],
)
def test_native_lane_rejects_unimplemented_python_coverage_instead_of_false_pass(lane, monkeypatch):
    monkeypatch.setattr(
        test_suite, "run", lambda *args: pytest.fail("no test command may run for an unsupported measurement")
    )
    with pytest.raises(ValueError, match="no admitted Python coverage"):
        test_suite.execute(lane, argparse.Namespace(coverage=True))


def test_current_workflow_aggregates_actual_owners_and_preserves_full_rust_vectors():
    # Reading the production workflow keeps these assertions on the actual CI caller.
    import yaml

    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/quality.yml").read_text())
    jobs = workflow["jobs"]
    assert {
        "rust-kernel",
        "python-contract",
        "database-compose",
        "research-product-certification",
        "private-asset-contract",
        "native-conformance",
        "research-evaluation-shard-gate",
    } <= set(jobs["native-quality-gate"]["needs"])
    assert "rust-kernel" in jobs["research-evaluation-shard-gate"]["needs"]
    rust_commands = [step.get("run", "") for step in jobs["rust-kernel"]["steps"]]
    assert "python scripts/dev_verification.py run -- python scripts/rust_kernel_check.py" in rust_commands
    shard_commands = "\n".join(step.get("run", "") for step in jobs["research-evaluation-shard-gate"]["steps"])
    assert "--collect-only --no-parallel" in shard_commands
    assert "--expected-nodeids-path" in shard_commands and '--expected-commit "$GITHUB_SHA"' in shard_commands
    for owner in ("private-asset-contract", "database-compose", "research-product-certification"):
        assert all(
            "tests/quant_assets" not in step.get("run", "") and "tests/certification" not in step.get("run", "")
            for step in jobs[owner]["steps"]
        )


def test_release_selects_each_complete_current_python_owner_without_legacy_aliases():
    assert set(test_suite.RELEASE_LANES) == {
        test_suite.OnlyTestLane.ARCHITECTURE,
        test_suite.OnlyTestLane.PYTHON_CONTRACT,
        test_suite.OnlyTestLane.PRIVATE_ASSET_CONTRACT,
        test_suite.OnlyTestLane.RESEARCH_EVALUATION,
        test_suite.OnlyTestLane.DATABASE,
        test_suite.OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION,
    }
    assert test_suite.LANES[test_suite.OnlyTestLane.DATABASE].workers == "0"
    assert all((test_suite.ROOT / path).is_file() for path in test_suite.LANES[test_suite.OnlyTestLane.DATABASE].paths)


def test_release_uses_actual_native_web_journey_and_fails_before_build(monkeypatch):
    args = argparse.Namespace(
        coverage=False,
        splits=None,
        group=None,
        collect_only=False,
        collection_path=None,
        store_durations=False,
        clean_durations=False,
    )
    calls = []
    monkeypatch.setattr(test_suite, "execute_release_check", lambda check: 0)

    def run(command, env=None):
        calls.append(command)
        return 19 if command == ["bash", "deploy/run-web-e2e.sh"] else 0

    monkeypatch.setattr(test_suite, "run", run)
    assert test_suite.release(args) == 19
    assert calls[-1] == ["bash", "deploy/run-web-e2e.sh"]
    assert list(test_suite.BUILD_COMMAND) not in calls
    assert not any(command[-2:] == ["scripts/web_suite.py", "e2e"] for command in calls)


@pytest.mark.parametrize(
    "lane,expected",
    [
        (
            test_suite.OnlyTestLane.DATABASE,
            [("probe", False), ("probe", True), ("main", False), ("main", True), ("http", None)],
        ),
        (
            test_suite.OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION,
            [
                ("probe", False),
                ("probe", True),
                ("main", True),
                ("science", False),
                ("science", True),
                ("backtest_owner_probe", True),
            ],
        ),
        (test_suite.OnlyTestLane.PYTHON_CONTRACT, [("main", True), ("http", None), ("trading", True)]),
        (test_suite.OnlyTestLane.PRIVATE_ASSET_CONTRACT, [("trading", True)]),
        (test_suite.OnlyTestLane.ARCHITECTURE, []),
    ],
)
def test_native_owner_builds_only_the_targets_its_real_fixtures_consume(monkeypatch, lane, expected):
    from packages.backend.tests.application import conftest as app
    from packages.backend.tests.application import test_strategy_research_evidence as science
    from packages.backend.tests.transport import conftest as transport
    from packages.backend.tests.workers import test_installed_trading_nodes as trading
    from scripts import native_http_contract

    calls = []
    monkeypatch.setattr(app, "build_native_probe", lambda *, release: calls.append(("probe", release)))
    monkeypatch.setattr(native_http_contract, "native_executable", lambda *, release: calls.append(("main", release)))
    monkeypatch.setattr(transport, "build_integration_http_probe", lambda: calls.append(("http", None)))

    def science_build(*, release, build_timeout, target_name="strategy_freeze_postgres"):
        assert build_timeout is None
        calls.append(("science" if target_name == "strategy_freeze_postgres" else target_name, release))

    def trading_build(*, release, build_timeout):
        assert build_timeout is None
        calls.append(("trading", release))

    monkeypatch.setattr(science, "_build_strategy_evidence_owner_binary", science_build)
    monkeypatch.setattr(trading, "build_installed_trading_binary", trading_build)
    test_suite.prepare_native_test_artifacts(lane)
    assert calls == expected


def test_all_workflow_job_dependencies_exist_and_final_gate_requires_native_owners():
    import yaml

    root = Path(__file__).resolve().parents[2]
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        jobs = yaml.safe_load(path.read_text()).get("jobs", {})
        for name, job in jobs.items():
            needs = job.get("needs", [])
            needs = [needs] if isinstance(needs, str) else needs
            assert set(needs) <= set(jobs), (path.name, name, set(needs) - set(jobs))
    jobs = yaml.safe_load((root / ".github/workflows/quality.yml").read_text())["jobs"]
    gate = jobs["quality-gate"]
    assert "native-quality-gate" in gate["needs"]
    step = gate["steps"][0]
    assert step["env"]["NATIVE_QUALITY_GATE_RESULT"] == "${{ needs.native-quality-gate.result }}"
    assert '"$NATIVE_QUALITY_GATE_RESULT" = success' in step["run"]
    assert "python-contract" in gate["needs"]
    assert step["env"]["PYTHON_CONTRACT_RESULT"] == "${{ needs.python-contract.result }}"
    assert '"$PYTHON_CONTRACT_RESULT" = success' in step["run"]
    native = jobs["native-quality-gate"]
    assert "python-contract" in native["needs"]
    assert native["steps"][0]["env"]["PYTHON_RESULT"] == "${{ needs.python-contract.result }}"
    assert '"$PYTHON_RESULT" = success' in native["steps"][0]["run"]
    python = jobs["python-contract"]
    assert "if" not in python, "push must execute this independent owner too"
    commands = [entry.get("run") for entry in python["steps"]]
    assert commands == [
        None,
        "python scripts/dev_verification.py prepare",
        "python scripts/dev_verification.py run -- python scripts/test_suite.py python-contract",
    ]


def test_verification_profile_discards_inherited_semantic_overrides_and_keeps_both_build_modes(tmp_path):
    from scripts.rust_kernel_check import compiler_environment

    env = compiler_environment(
        {
            "CARGO_PROFILE_DEV_OPT_LEVEL": "3",
            "CARGO_PROFILE_TEST_DEBUG_ASSERTIONS": "false",
            "CARGO_PROFILE_DEV_OVERFLOW_CHECKS": "false",
            "RUSTFLAGS": "-C overflow-checks=off",
        },
        tmp_path / "target",
    )
    assert env["CARGO_PROFILE_DEV_DEBUG"] == env["CARGO_PROFILE_TEST_DEBUG"] == "0"
    assert (
        not {
            "CARGO_PROFILE_DEV_OPT_LEVEL",
            "CARGO_PROFILE_TEST_DEBUG_ASSERTIONS",
            "CARGO_PROFILE_DEV_OVERFLOW_CHECKS",
            "RUSTFLAGS",
        }
        & env.keys()
    )
    assert not any(key.startswith("CARGO_PROFILE_RELEASE_") for key in env)


def test_script_entry_resolves_native_fixture_modules_without_inherited_python_path(tmp_path):
    import subprocess
    import sys

    entry = test_suite.ROOT / "scripts/test_suite.py"
    code = f"import runpy; runpy.run_path({str(entry)!r}); import packages.backend.tests.application.conftest; import packages.backend.tests.transport.conftest"
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def impact_plan(path, *, kind=verify.ChangeKind.MODIFIED, old_path=None):
    return verify.plan_for_change_set(
        verify.VerificationChangeSet("current-head", (verify.VerificationChangedPath(path, kind, old_path),), True)
    )


@pytest.mark.parametrize("path", ["crates/operators/src/lib.rs", "crates/indicators/src/lib.rs"])
def test_current_impact_native_operators_select_actual_cargo_owners_without_retired_lanes(path):
    from scripts.rust_kernel_check import affected_packages

    plan = impact_plan(path)
    assert plan.impact.lanes == ()
    assert test_suite.OnlyReleaseCheck.RUST_KERNEL in plan.impact.checks
    commands = dict(verify.verification_commands(plan))
    command = commands["check:rust-selected"]
    actual = tuple(command[index + 1] for index, value in enumerate(command) if value == "--package")
    assert actual == affected_packages(verify.ROOT, (path,))
    assert actual and "--source-check" not in command


@pytest.mark.parametrize(
    "path",
    [
        "packages/backend/src/application/watchlists.rs",
        "packages/backend/src/persistence/watchlist_postgres.rs",
        "packages/backend/src/transport/integrations.rs",
        "packages/backend/src/bootstrap/deployment.rs",
        "packages/backend/Cargo.toml",
    ],
)
def test_current_impact_native_product_keeps_real_database_and_web_proof_boundaries(path):
    plan = impact_plan(path)
    assert set(plan.impact.lanes) == {
        test_suite.OnlyTestLane.DATABASE,
        test_suite.OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION,
    }
    assert test_suite.OnlyReleaseCheck.RUST_KERNEL in plan.impact.checks
    assert set(verify.WEB_CHECKS) <= set(plan.impact.checks)
    with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
        verify.verification_commands(plan)


@pytest.mark.parametrize(
    "path",
    [
        "packages/backend/python/algorithms/sdk/onlyalpha/canonical.py",
        "packages/backend/python/algorithms/src/onlyalpha_backend_algorithms/targets/research.py",
        "packages/backend/python/gateway_protocol/src/onlyalpha_gateway_protocol/client.py",
        "examples/private-assets/factor/simple_momentum/source.py",
        "packages/backend/tests/transport/test_authoring_session_protocol.py",
    ],
)
def test_current_impact_python_and_abi_select_the_existing_complete_python_owners(path):
    plan = impact_plan(path)
    owners = {
        test_suite.OnlyTestLane.PYTHON_CONTRACT,
        test_suite.OnlyTestLane.PRIVATE_ASSET_CONTRACT,
        test_suite.OnlyTestLane.RESEARCH_EVALUATION,
    }
    assert set(plan.impact.lanes) == owners
    assert test_suite.OnlyReleaseCheck.RUST_KERNEL not in plan.impact.checks
    assert not set(verify.WEB_CHECKS).intersection(plan.impact.checks)
    commands = verify.verification_commands(plan)
    assert {gate for gate, _ in commands if gate.startswith("lane:")} == {f"lane:{owner.value}" for owner in owners}
    assert all(not arg.startswith(("src/", "tests/")) for _, command in commands for arg in command)


@pytest.mark.parametrize(
    "path",
    [
        "database/postgres/migrations/0001_schema.sql",
        "packages/backend/tests/application/test_watchlist_postgres.py",
        "packages/backend/tests/application/test_strategy_research_evidence.py",
    ],
)
def test_current_impact_database_uses_serial_actual_owners_without_legacy_research_postgres(path):
    plan = impact_plan(path)
    assert set(plan.impact.lanes) == {
        test_suite.OnlyTestLane.DATABASE,
        test_suite.OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION,
    }
    assert test_suite.OnlyReleaseCheck.RUST_KERNEL not in plan.impact.checks
    with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
        verify.verification_commands(plan)


@pytest.mark.parametrize("path", ["contracts/product-api/v2/openapi.json", "packages/frontend/src/main.tsx"])
def test_current_impact_public_api_and_web_keep_actual_web_gates_and_explicit_scope_review(path):
    plan = impact_plan(path)
    assert set(verify.WEB_CHECKS) <= set(plan.impact.checks)
    with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
        verify.verification_commands(plan)


def test_current_impact_rules_never_select_retired_lanes_or_retired_source_roots():
    current = set(test_suite.RELEASE_LANES)
    for rule in verify.IMPACT_RULES:
        assert set(rule.lanes) <= current
        assert all(not path.startswith(("src/", "tests/")) for path in (*rule.prefixes, *rule.exact_paths))


@pytest.mark.parametrize("path", ["unknown/new.py", "src/onlyalpha/research/run.py", "tests/research/test_old.py"])
def test_current_impact_unknown_and_retired_paths_refuse_run_before_any_check(path, monkeypatch):
    plan = impact_plan(path)
    assert any(reason.rule == "manual-impact-review-required" for reason in plan.impact.reasons)
    monkeypatch.setattr(verify, "resolve_change_set", lambda: plan.change_set)
    monkeypatch.setattr(verify, "_run_step", lambda *a, **kw: pytest.fail("unknown scope started a check"))
    monkeypatch.setattr(verify.sys, "argv", ["verify.py", "run"])
    assert verify.main() == 2


def test_current_impact_renames_preserve_both_owner_relations_but_only_check_the_new_python_name():
    old = "packages/backend/python/algorithms/sdk/onlyalpha/old.py"
    new = "packages/backend/python/gateway_protocol/src/onlyalpha_gateway_protocol/new.py"
    plan = impact_plan(new, kind=verify.ChangeKind.RENAMED, old_path=old)
    assert {reason.path for reason in plan.impact.reasons} == {old, new}
    commands = verify.verification_commands(plan)
    ruff = dict(commands)["check:affected-ruff"]
    assert new in ruff and old not in ruff


def test_current_impact_quality_infrastructure_requires_current_architecture_owner_and_review():
    plan = impact_plan("scripts/verify.py")
    assert plan.impact.lanes == (test_suite.OnlyTestLane.ARCHITECTURE,)
    with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
        verify.verification_commands(plan)


def test_current_impact_undeclared_native_owner_refuses_before_any_check(monkeypatch):
    plan = impact_plan("crates/undeclared/src/lib.rs")
    monkeypatch.setattr(verify, "resolve_change_set", lambda: plan.change_set)
    monkeypatch.setattr(verify, "_run_step", lambda *a, **kw: pytest.fail("unmapped Cargo owner started a check"))
    monkeypatch.setattr(verify.sys, "argv", ["verify.py", "run"])
    assert verify.main() == 2


def test_current_impact_mixed_research_algorithm_scenarios_keep_postgres_and_offline_owners():
    from _pytest.mark.expression import Expression

    path = "packages/backend/tests/application/test_research_algorithm_execution.py"
    plan = impact_plan(path)
    assert set(plan.impact.lanes) == {
        test_suite.OnlyTestLane.PYTHON_CONTRACT,
        test_suite.OnlyTestLane.PRIVATE_ASSET_CONTRACT,
        test_suite.OnlyTestLane.RESEARCH_EVALUATION,
        test_suite.OnlyTestLane.DATABASE,
        test_suite.OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION,
    }
    assert plan.impact.escalation is verify.VerificationEscalation.BROAD
    with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
        verify.verification_commands(plan)

    # Derive the actual mixed marker universe from the maintained scenarios.
    # Evaluate the real lane expressions with pytest's own marker expression engine.
    source = ast.parse((test_suite.ROOT / path).read_text())

    def marker_names(nodes):
        return {
            node.attr
            for parent in nodes
            for node in ast.walk(parent)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "mark"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "pytest"
        }

    module_markers = marker_names(
        statement.value
        for statement in source.body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in statement.targets)
    )
    scenarios = {
        function.name: module_markers | marker_names(function.decorator_list)
        for function in source.body
        if isinstance(function, ast.FunctionDef) and function.name.startswith("test_")
    }
    assert any("postgres" in markers for markers in scenarios.values())
    assert any("postgres" not in markers for markers in scenarios.values())
    for name, markers in scenarios.items():
        admitted = set()
        for owner in plan.impact.lanes:
            lane = test_suite.LANES[owner]
            contains_file = any(
                Path(path) == Path(entry.split("::")[0]) or Path(entry.split("::")[0]) in Path(path).parents
                for entry in lane.paths
            )
            if contains_file and Expression.compile(lane.expression).evaluate(
                lambda marker, selected_markers=markers, **kw: marker in selected_markers
            ):
                admitted.add(owner)
        if "postgres" in markers:
            assert admitted == {test_suite.OnlyTestLane.DATABASE}, (name, markers, admitted)
        else:
            assert admitted == {
                test_suite.OnlyTestLane.PYTHON_CONTRACT,
                test_suite.OnlyTestLane.RESEARCH_EVALUATION,
            }, (name, markers, admitted)


def test_release_discovers_every_current_backend_test():
    root = test_suite.ROOT
    selected = set()
    for lane in test_suite.RELEASE_LANES:
        for argument in test_suite.LANES[lane].paths:
            path = root / argument.split("::", 1)[0]
            selected.update(path.rglob("test_*.py") if path.is_dir() else [path])
    discovered = set((root / "packages/backend").rglob("test_*.py"))
    assert discovered
    assert not discovered - selected, sorted(path.relative_to(root).as_posix() for path in discovered - selected)
    owner = test_suite.LANES[test_suite.OnlyTestLane.PYTHON_CONTRACT]
    assert {
        "packages/backend/tests/transport/test_native_web_assets.py",
        "packages/backend/tests/transport/test_native_process_startup.py",
    } <= set(owner.paths)
    # The real file-level markers must survive the real lane expression.
    from _pytest.mark.expression import Expression

    expression = Expression.compile(owner.expression)
    for relative in ("test_native_web_assets.py", "test_native_process_startup.py"):
        tree = ast.parse((root / "packages/backend/tests/transport" / relative).read_text())
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets)
        )
        markers = {
            node.attr
            for node in ast.walk(assignment.value)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "pytest"
            and node.value.attr == "mark"
        }
        assert "integration" in markers
        assert expression.evaluate(markers.__contains__)


def _capture_web_wrapper(tmp_path, arguments=(), *, fail_at=0):
    """Execute the real Bash wrapper, recording its process argv without Web/Docker."""
    import os
    import subprocess

    root = Path(__file__).resolve().parents[2]
    wrapper = tmp_path / "deploy/run-web-e2e.sh"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_bytes((root / "deploy/run-web-e2e.sh").read_bytes())
    executables = tmp_path / "bin"
    executables.mkdir()
    record = tmp_path / "argv.jsonl"
    stub = executables / "python"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "record = pathlib.Path(os.environ['WEB_WRAPPER_ARGV_LOG'])\n"
        "calls = record.read_text().splitlines() if record.exists() else []\n"
        "with record.open('a') as output: output.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.exit(19 if len(calls) + 1 == int(os.environ['WEB_WRAPPER_FAIL_AT']) else 0)\n"
    )
    stub.chmod(0o700)
    result = subprocess.run(
        ["bash", str(wrapper), *arguments],
        env={
            **os.environ,
            "PATH": str(executables) + os.pathsep + os.environ["PATH"],
            "WEB_WRAPPER_ARGV_LOG": str(record),
            "WEB_WRAPPER_FAIL_AT": str(fail_at),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result, [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []


def _native_web_arguments(call):
    # The actual outer admission flag must precede mode, and the native command
    # must use the module form recognized by the existing controlled guard.
    prefix = ["scripts/dev_verification.py"]
    if "--controlled-source-https" in call[:3]:
        prefix.append("--controlled-source-https")
    prefix += ["run", "--", "python", "-m", "scripts.native_web_e2e"]
    assert call[: len(prefix)] == prefix
    return call[len(prefix) :]


def test_default_web_wrapper_partitions_all_specs_and_preserves_real_restart_and_performance_owners(tmp_path):
    import re

    from scripts.dev_verification import controlled_https_command

    result, calls = _capture_web_wrapper(tmp_path)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 5
    batches = [_native_web_arguments(call) for call in calls]
    specs = [[argument for argument in batch if argument.endswith(".spec.ts")] for batch in batches]
    ordinary = {
        "e2e/analysis.spec.ts",
        "e2e/chart-catalog.spec.ts",
        "e2e/data-sources.spec.ts",
        "e2e/factor-http-boundaries.spec.ts",
        "e2e/factors.spec.ts",
        "e2e/market-data-historical.spec.ts",
        "e2e/market-data-realtime.spec.ts",
        "e2e/metadata-errors.spec.ts",
        "e2e/product-package-migration.spec.ts",
        "e2e/product-workspaces.spec.ts",
        "e2e/research.spec.ts",
        "e2e/source-command-errors.spec.ts",
        "e2e/study-renderer.spec.ts",
        "e2e/workspace-toolbar.spec.ts",
    }
    assert len(specs[0]) == len(ordinary) == 14 and set(specs[0]) == ordinary
    assert specs[1:] == [
        ["e2e/private-factor-authoring.spec.ts"],
        ["e2e/chart-native-sma.spec.ts"],
        ["e2e/backtest.spec.ts"],
        ["e2e/backtest.spec.ts"],
    ]
    discovered = {
        path.relative_to(test_suite.ROOT / "packages/frontend").as_posix()
        for path in (test_suite.ROOT / "packages/frontend/e2e").rglob("*.spec.ts")
    }
    assert len(discovered) == 17
    assert set().union(*map(set, specs)) == discovered
    assert not ordinary & set().union(*map(set, specs[1:]))
    assert batches[0] == sorted(ordinary)
    assert batches[1] == ["--restart-check", "e2e/private-factor-authoring.spec.ts"]
    assert batches[2] == [
        "--controlled-source-https",
        "--retained-market-input",
        "--chart-sma-market-input",
        "e2e/chart-native-sma.spec.ts",
    ]
    titles = re.findall(r'test\("([^"]+)"', (test_suite.ROOT / "packages/frontend/e2e/backtest.spec.ts").read_text())
    functional_titles = [
        "normal backtest functional correctness reopens the same run after restart",
        "normal backtest functional cancellation reopens the same cancelled run after restart",
        "normal backtest functional running recovery completes the same run after restart",
    ]
    performance_title = "normal backtest works without Agent and reopens the same run after restart"
    assert set(titles) == {*functional_titles, performance_title}
    # Recovery runs last: the existing harness drains its original host after
    # the initial browser batch, then starts the restored browser batch.
    assert titles[-1] == functional_titles[-1]
    selections = [
        (
            "normal backtest functional (correctness reopens the same run|"
            "cancellation reopens the same cancelled run|"
            "running recovery completes the same run) after restart$",
            functional_titles,
        ),
        (performance_title + "$", [performance_title]),
    ]
    for batch, (pattern, selected) in zip(batches[3:], selections, strict=True):
        assert batch == [
            "--controlled-source-https",
            "--retained-market-input",
            "--backtest-market-input",
            "--restart-check",
            "e2e/backtest.spec.ts",
            "--grep",
            pattern,
        ]
        assert [title for title in titles if re.search(pattern, "backtest.spec.ts " + title)] == selected
    for index, (call, batch) in enumerate(zip(calls, batches, strict=True)):
        controlled = index >= 2
        assert ("--controlled-source-https" in call[:3]) is controlled
        assert controlled_https_command(["python", "-m", "scripts.native_web_e2e", *batch]) is controlled


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4, 5])
def test_web_wrapper_stops_on_each_failed_batch_including_mandatory_performance(tmp_path, fail_at):
    result, calls = _capture_web_wrapper(tmp_path, fail_at=fail_at)
    assert result.returncode == 19
    assert len(calls) == fail_at


@pytest.mark.parametrize(
    "arguments,controlled",
    [
        (["e2e/analysis.spec.ts"], False),
        (["--contract-fuzz"], False),
        (["--restart-check", "e2e/private-factor-authoring.spec.ts"], False),
        (
            [
                "--controlled-source-https",
                "--retained-market-input",
                "--chart-sma-market-input",
                "e2e/chart-native-sma.spec.ts",
            ],
            True,
        ),
        (
            [
                "--controlled-source-https",
                "--retained-market-input",
                "--backtest-market-input",
                "--restart-check",
                "e2e/backtest.spec.ts",
                "--grep",
                "normal backtest functional correctness",
            ],
            True,
        ),
    ],
)
def test_custom_web_wrapper_runs_only_the_explicit_selection_with_exact_controlled_admission(
    tmp_path, arguments, controlled
):
    result, calls = _capture_web_wrapper(tmp_path, arguments)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    assert _native_web_arguments(calls[0]) == arguments
    assert ("--controlled-source-https" in calls[0][:3]) is controlled


def test_custom_web_wrapper_propagates_failure_without_running_default_batches(tmp_path):
    result, calls = _capture_web_wrapper(tmp_path, ["e2e/analysis.spec.ts"], fail_at=1)
    assert result.returncode == 19
    assert len(calls) == 1


def test_functional_web_wrapper_runs_the_complete_functional_plan_without_performance(tmp_path):
    default, full = _capture_web_wrapper(tmp_path / "default")
    functional, selected = _capture_web_wrapper(tmp_path / "functional", ["--functional-only"])
    assert default.returncode == functional.returncode == 0
    assert len(full) == 5 and len(selected) == 4
    assert selected == full[:4]
    assert _native_web_arguments(selected[-1])[-1] == (
        "normal backtest functional (correctness reopens the same run|"
        "cancellation reopens the same cancelled run|"
        "running recovery completes the same run) after restart$"
    )
    assert all("--functional-only" not in call for call in selected)
    assert not any(
        "normal backtest works without Agent and reopens the same run after restart$" in call for call in selected
    )


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_functional_web_wrapper_stops_at_each_failed_functional_batch(tmp_path, fail_at):
    result, calls = _capture_web_wrapper(tmp_path, ["--functional-only"], fail_at=fail_at)
    assert result.returncode == 19
    assert len(calls) == fail_at


@pytest.mark.parametrize(
    "arguments",
    [
        ["--functional-only", "e2e/analysis.spec.ts"],
        ["e2e/analysis.spec.ts", "--functional-only"],
        ["--functional-only", "--functional-only"],
        ["--functional-only", "--grep", "normal backtest works"],
    ],
)
def test_functional_web_wrapper_rejects_ambiguous_selections_before_startup(tmp_path, arguments):
    result, calls = _capture_web_wrapper(tmp_path, arguments)
    assert result.returncode == 2
    assert calls == []
    assert "--functional-only must be used alone" in result.stderr


def test_nightly_mutation_guard_and_campaign_use_the_same_fixed_environment():
    import yaml

    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/nightly.yml").read_text())
    job = workflow["jobs"]["mutation"]
    assert job["timeout-minutes"] == 180
    assert not job.get("if") and not job.get("continue-on-error", False)
    steps = job["steps"]
    assert steps[0]["uses"] == "actions/checkout@v6"
    assert steps[0]["with"]["fetch-depth"] == 0
    # Exact argv and ordering reject host pytest/cargo, a missing prepare,
    # shell failure suppression, and a campaign that bypasses its guard.
    assert [step["run"] for step in steps if "run" in step] == [
        "python scripts/dev_verification.py prepare",
        "python scripts/dev_verification.py run -- python -m pytest -q scripts/tests/test_domain_mutation.py",
        "python scripts/dev_verification.py run -- python scripts/domain_mutation.py",
    ]
    for step in steps:
        assert not step.get("continue-on-error", False)
        if "run" in step:
            assert not step.get("if")
    artifact = steps[-1]
    assert artifact["uses"] == "actions/upload-artifact@v6"
    assert artifact["if"] == "always()"
    assert artifact["with"]["path"] == "test-results/domain-mutation/"
    assert artifact["with"]["if-no-files-found"] == "error"
    dockerfile = (root / "deploy/Dockerfile.dev").read_text()
    assert "RUN CARGO_NET_RETRY=0 cargo install --locked --version 27.1.0 cargo-mutants" in dockerfile
    assert "COPY --from=rust-tools /usr/local/cargo /usr/local/cargo" in dockerfile


def _paused_backtest_observation():
    return {
        "run_id": "00000000-0000-4000-8000-000000000001",
        "binding": {"work_id": "00000000-0000-4000-8000-000000000001"},
        "execution_prefix": [{"sequence": 1, "logical_digest": "a" * 64, "ready": True}],
        "replay_prefix": [{"sequence": 1, "digest": "b" * 64, "logical_digest": "c" * 64, "ready": True}],
        "steps": [
            {"sequence": 1, "kind": "PAUSE", "status": "PAUSED", "input_finished": False, "input_cancelled": False}
        ],
        "state": {"status": "PAUSED", "input_finished": False, "outcome": None},
    }


@pytest.mark.parametrize(
    "invalid", ["none", "completed", "finished", "cancelled", "no-execution", "no-replay", "outcome"]
)
def test_running_web_recovery_requires_actual_drained_pause_instead_of_natural_completion(invalid):
    from scripts.native_web_e2e import require_paused_backtest

    observed = _paused_backtest_observation()
    if invalid == "completed":
        observed["steps"][-1].update(kind="TERMINATE", status="TERMINATED")
        observed["state"].update(status="TERMINATED", outcome={"status": "COMPLETED"})
    elif invalid == "finished":
        observed["steps"][-1]["input_finished"] = True
    elif invalid == "cancelled":
        observed["steps"][-1]["input_cancelled"] = True
    elif invalid == "no-execution":
        observed["execution_prefix"] = []
    elif invalid == "no-replay":
        observed["replay_prefix"] = []
    elif invalid == "outcome":
        observed["state"]["outcome"] = {"status": "COMPLETED"}
    if invalid == "none":
        require_paused_backtest(observed)
    else:
        with pytest.raises(AssertionError):
            require_paused_backtest(observed)


@pytest.mark.parametrize(
    "invalid", ["none", "run", "binding", "execution", "replay", "old-step", "no-resume", "failed"]
)
def test_running_web_recovery_retains_original_prefix_and_requires_actual_resume_then_completion(invalid):
    import copy

    from scripts.native_web_e2e import require_resumed_backtest

    before = _paused_backtest_observation()
    after = copy.deepcopy(before)
    after["steps"] += [
        {"sequence": 2, "kind": "RESUME", "status": "RUNNING"},
        {"sequence": 3, "kind": "TERMINATE", "status": "TERMINATED"},
    ]
    after["state"] = {"outcome": {"status": "COMPLETED"}}
    if invalid == "run":
        after["run_id"] = "00000000-0000-4000-8000-000000000002"
    elif invalid == "binding":
        after["binding"]["work_id"] = "foreign"
    elif invalid == "execution":
        after["execution_prefix"][0]["logical_digest"] = "d" * 64
    elif invalid == "replay":
        after["replay_prefix"][0]["digest"] = "d" * 64
    elif invalid == "old-step":
        after["steps"][0]["status"] = "RUNNING"
    elif invalid == "no-resume":
        after["steps"].pop(1)
    elif invalid == "failed":
        after["state"]["outcome"]["status"] = "FAILED"
    if invalid == "none":
        require_resumed_backtest(before, after)
    else:
        with pytest.raises(AssertionError):
            require_resumed_backtest(before, after)
