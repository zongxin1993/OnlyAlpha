from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.test_suite import OnlyReleaseCheck, OnlyTestLane, release_check_commands  # noqa: E402


class VerificationEscalation(IntEnum):
    DOCS_ONLY = 0
    COMPONENT = 1
    BROAD = 2
    QUALITY_INFRASTRUCTURE = 3


class ChangeKind(StrEnum):
    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"
    UNTRACKED = "untracked"


@dataclass(frozen=True, slots=True)
class VerificationChangedPath:
    path: str
    kind: ChangeKind = ChangeKind.MODIFIED
    old_path: str | None = None

    def impact_paths(self) -> tuple[str, ...]:
        return (self.path,) if self.old_path is None else tuple(sorted((self.old_path, self.path)))

    def as_json(self) -> dict[str, object]:
        return {"path": self.path, "kind": self.kind.value, "old_path": self.old_path}


@dataclass(frozen=True, slots=True)
class VerificationChangeSet:
    head_revision: str
    changed_paths: tuple[VerificationChangedPath, ...]
    dirty_worktree: bool

    def as_json(self) -> dict[str, object]:
        return {
            "head_revision": self.head_revision,
            "dirty_worktree": self.dirty_worktree,
            "changed_files": [item.as_json() for item in self.changed_paths],
        }


@dataclass(frozen=True, slots=True)
class VerificationImpactRule:
    name: str
    prefixes: tuple[str, ...]
    exact_paths: tuple[str, ...]
    lanes: tuple[OnlyTestLane, ...]
    checks: tuple[OnlyReleaseCheck, ...]
    escalation: VerificationEscalation
    rationale: str
    excluded_paths: tuple[str, ...] = ()

    def matches(self, path: str) -> bool:
        return path not in self.excluded_paths and (
            path in self.exact_paths or any(path.startswith(prefix) for prefix in self.prefixes)
        )


@dataclass(frozen=True, slots=True)
class ImpactReason:
    path: str
    rule: str
    rationale: str

    def as_json(self) -> dict[str, str]:
        return {"path": self.path, "rule": self.rule, "rationale": self.rationale}


@dataclass(frozen=True, slots=True)
class VerificationStaticPlan:
    ruff_targets: tuple[str, ...] = ()
    format_targets: tuple[str, ...] = ()
    mypy_targets: tuple[str, ...] = ()
    import_linter_required: bool = False
    version_sync_required: bool = False
    build_targets: tuple[str, ...] = ()

    def as_json(self) -> dict[str, object]:
        return {
            "ruff_targets": list(self.ruff_targets),
            "format_targets": list(self.format_targets),
            "mypy_targets": list(self.mypy_targets),
            "import_linter_required": self.import_linter_required,
            "version_sync_required": self.version_sync_required,
            "build_targets": list(self.build_targets),
        }


@dataclass(frozen=True, slots=True)
class VerificationImpact:
    lanes: tuple[OnlyTestLane, ...]
    checks: tuple[OnlyReleaseCheck, ...]
    reasons: tuple[ImpactReason, ...]
    escalation: VerificationEscalation
    static_plan: VerificationStaticPlan | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "selected_checks": [item.value for item in self.checks],
            "selected_lanes": [item.value for item in self.lanes],
            "escalation": self.escalation.name,
            "matched_rules": [item.as_json() for item in self.reasons],
            "static_plan": None if self.static_plan is None else self.static_plan.as_json(),
        }


@dataclass(frozen=True, slots=True)
class VerificationPlan:
    change_set: VerificationChangeSet
    impact: VerificationImpact

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "authority": "IMPACT_SELECTION_ONLY",
            "change_set": self.change_set.as_json(),
            "impact": self.impact.as_json(),
        }


@dataclass(frozen=True, slots=True)
class VerificationStepResult:
    gate: str
    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float
    output: str
    collected: int | None = None


STATIC = (OnlyReleaseCheck.STATIC,)
WEB_CHECKS = (
    OnlyReleaseCheck.WEB_STATIC,
    OnlyReleaseCheck.WEB_UNIT,
    OnlyReleaseCheck.WEB_BUILD,
    OnlyReleaseCheck.WEB_E2E,
)
IMPACT_RULES = (
    VerificationImpactRule(
        "rust-kernel",
        (
            "crates/",
            "packages/backend/src/",
            "packages/backend/tests/",
            "plugs/",
            "test-data/predicate/",
            "test-data/domain/",
            "test-data/clock/",
            "test-data/event/",
            "test-data/market-data-state/",
            "test-data/market-data-construction/",
            "test-data/market-data-delivery/",
            "test-data/market-data-pipeline/",
            "test-data/strategy/",
            "test-data/calculation/",
            "test-data/order/",
            "test-data/position/",
            "test-data/account/",
            "test-data/strategy-ledger/",
            "test-data/risk/",
            "test-data/execution/",
            "test-data/broker/",
            "test-data/fee/",
            "test-data/settlement/",
            "test-data/margin/",
            "test-data/runtime/",
            "test-data/backtest/",
            "contracts/gateway/",
        ),
        (
            "Cargo.toml",
            "Cargo.lock",
            "rust-toolchain.toml",
            "packages/backend/Cargo.toml",
            "scripts/rust_kernel_check.py",
            "scripts/backtest_replay_check.py",
            "scripts/execution_reference_check.py",
            "scripts/broker_reference_check.py",
            "scripts/fee_reference_check.py",
            "scripts/settlement_reference_check.py",
            "scripts/margin_reference_check.py",
            "scripts/strategy_execution_check.py",
            "scripts/gateway_protocol.py",
        ),
        (),
        (OnlyReleaseCheck.STATIC, OnlyReleaseCheck.RUST_KERNEL),
        VerificationEscalation.COMPONENT,
        "Native source and fixtures use the existing Cargo owner/direct-consumer selector",
    ),
    VerificationImpactRule(
        "quality-infrastructure",
        (".github/workflows/", "scripts/"),
        ("AGENTS.md", "quality-policy.toml"),
        (OnlyTestLane.ARCHITECTURE,),
        STATIC,
        VerificationEscalation.QUALITY_INFRASTRUCTURE,
        "Verification infrastructure requires its current architecture contracts and explicit impact review",
    ),
    VerificationImpactRule(
        "python-contract",
        (
            "packages/backend/python/",
            "examples/private-assets/",
            "test-data/external_plugins/",
            "test-data/runtime_factor_provider/",
        ),
        (
            "packages/backend/tests/transport/test_authoring_session_protocol.py",
            "packages/backend/tests/transport/test_trading_algorithm_session.py",
            "packages/backend/tests/transport/test_trading_algorithm_transport.py",
            "packages/backend/tests/transport/test_chart_algorithm_closure.py",
            "packages/backend/tests/workers/test_installed_trading_nodes.py",
            "packages/backend/tests/application/test_research_algorithm_execution.py",
        ),
        (OnlyTestLane.PYTHON_CONTRACT, OnlyTestLane.PRIVATE_ASSET_CONTRACT, OnlyTestLane.RESEARCH_EVALUATION),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Maintained SDK/runner/protocol and examples use their real Python/ABI and research owners",
    ),
    VerificationImpactRule(
        "database-owner",
        (
            "database/postgres/",
            "packages/backend/src/persistence/",
            "packages/backend/src/bootstrap/",
            "packages/backend/tests/application/",
        ),
        (),
        (OnlyTestLane.DATABASE, OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION),
        STATIC,
        VerificationEscalation.BROAD,
        "Durable application facts require current serial database and research product owners",
    ),
    VerificationImpactRule(
        "product-api",
        (
            "packages/backend/src/",
            "packages/backend/tests/transport/",
            "contracts/product-api/",
        ),
        ("packages/backend/Cargo.toml", "scripts/openapi_contract.py", "scripts/tests/test_openapi_contract.py"),
        (OnlyTestLane.DATABASE, OnlyTestLane.RESEARCH_PRODUCT_CERTIFICATION),
        WEB_CHECKS,
        VerificationEscalation.BROAD,
        "Formal Product API changes require native/DB and Web consumers; compatibility needs an explicit exact baseline",
        (
            "packages/backend/tests/transport/test_authoring_session_protocol.py",
            "packages/backend/tests/transport/test_trading_algorithm_session.py",
            "packages/backend/tests/transport/test_trading_algorithm_transport.py",
            "packages/backend/tests/transport/test_chart_algorithm_closure.py",
        ),
    ),
    VerificationImpactRule(
        "web-product",
        ("packages/frontend/",),
        (),
        (),
        WEB_CHECKS,
        VerificationEscalation.COMPONENT,
        "Formal Web changes retain static/unit/build and actual Web journey verification",
    ),
    VerificationImpactRule(
        "package-metadata",
        (),
        ("pyproject.toml", "uv.lock"),
        (),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Distribution metadata retains consistency/build checks and explicit impact review",
    ),
    VerificationImpactRule(
        "docs-only",
        ("docs/",),
        ("README.md",),
        (),
        (),
        VerificationEscalation.DOCS_ONLY,
        "Long-lived documentation does not implicitly change executable Runtime semantics",
    ),
)


def plan_for_change_set(change_set: VerificationChangeSet) -> VerificationPlan:
    change_set = VerificationChangeSet(
        change_set.head_revision,
        tuple(sorted(change_set.changed_paths, key=lambda item: (item.path, item.kind.value, item.old_path or ""))),
        change_set.dirty_worktree,
    )
    lane_set: set[OnlyTestLane] = set()
    check_set: set[OnlyReleaseCheck] = set()
    reasons: list[ImpactReason] = []
    escalation = VerificationEscalation.DOCS_ONLY

    for changed in change_set.changed_paths:
        for path in changed.impact_paths():
            matched = tuple(rule for rule in IMPACT_RULES if rule.matches(path))
            # Python fixtures/ABI have explicit current owners; their test files
            # are not inputs to the Cargo-only owner selector.
            if path.startswith("packages/backend/tests/") and not path.endswith(".rs"):
                matched = tuple(rule for rule in matched if rule.name != "rust-kernel")
            if not matched:
                matched = (_unknown_rule(path),)
            for rule in matched:
                lane_set.update(rule.lanes)
                check_set.update(rule.checks)
                escalation = max(escalation, rule.escalation)
                reasons.append(ImpactReason(path, rule.name, rule.rationale))

    lanes = tuple(lane for lane in OnlyTestLane if lane in lane_set)
    checks = tuple(check for check in OnlyReleaseCheck if check in check_set)
    static_plan = _static_plan(change_set, tuple(reason.rule for reason in reasons), escalation)
    return VerificationPlan(
        change_set,
        VerificationImpact(
            lanes,
            checks,
            tuple(sorted(set(reasons), key=lambda item: (item.path, item.rule))),
            escalation,
            static_plan,
        ),
    )


def _unknown_rule(path: str) -> VerificationImpactRule:
    return VerificationImpactRule(
        "manual-impact-review-required",
        (),
        (path,),
        (),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Unclassified path gets affected static checks only; AGENTS.md requires manual Impact Scope review instead of automatic full-repo escalation",
    )


def _static_plan(
    change_set: VerificationChangeSet,
    rule_names: tuple[str, ...],
    escalation: VerificationEscalation,
) -> VerificationStaticPlan | None:
    if escalation is VerificationEscalation.DOCS_ONLY:
        return None

    rules = set(rule_names)
    metadata_paths = {
        path
        for changed in change_set.changed_paths
        for path in changed.impact_paths()
        if path
        in {
            "pyproject.toml",
            "uv.lock",
        }
    }
    version_sync_required = "package-metadata" in rules or any(
        path in {"Cargo.toml", "Cargo.lock"} for changed in change_set.changed_paths for path in changed.impact_paths()
    )
    build_targets = ("onlyalpha",) if metadata_paths else ()
    if escalation >= VerificationEscalation.BROAD:
        return VerificationStaticPlan(
            version_sync_required=version_sync_required,
            build_targets=build_targets,
        )

    changed_python = tuple(
        sorted(
            {
                path
                for changed in change_set.changed_paths
                for path in (changed.path,)
                if path.endswith(".py") and changed.kind is not ChangeKind.DELETED
            }
        )
    )
    typed_roots = {
        "python-contract": (
            "packages/backend/python/algorithms/sdk/onlyalpha",
            "packages/backend/python/algorithms/src/onlyalpha_backend_algorithms",
            "packages/backend/python/gateway_protocol/src/onlyalpha_gateway_protocol",
        ),
    }
    mypy_targets = tuple(sorted({target for rule in rules for target in typed_roots.get(rule, ())}))
    architecture = any(
        path.startswith("scripts/tests/") for changed in change_set.changed_paths for path in changed.impact_paths()
    )
    return VerificationStaticPlan(
        ruff_targets=changed_python,
        format_targets=changed_python,
        mypy_targets=mypy_targets,
        import_linter_required=architecture,
        version_sync_required=version_sync_required,
        build_targets=build_targets,
    )


def resolve_change_set() -> VerificationChangeSet:
    head_revision = _git("rev-parse", "HEAD").strip()
    changes: dict[tuple[str, str | None], VerificationChangedPath] = {}

    for args in (
        ("diff", "--cached", "--name-status", "-z", "--find-renames"),
        ("diff", "--name-status", "-z", "--find-renames"),
    ):
        for item in _parse_name_status(_git_bytes(*args)):
            changes[(item.path, item.old_path)] = item

    for raw in _git_bytes("ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if raw:
            path = raw.decode("utf-8")
            changes[(path, None)] = VerificationChangedPath(path, ChangeKind.UNTRACKED)

    dirty = bool(_git("status", "--porcelain=v1", "--untracked-files=all"))
    return VerificationChangeSet(
        head_revision,
        tuple(sorted(changes.values(), key=lambda item: (item.path, item.kind.value, item.old_path or ""))),
        dirty,
    )


def _parse_name_status(payload: bytes) -> tuple[VerificationChangedPath, ...]:
    fields = payload.split(b"\0")
    index = 0
    result: list[VerificationChangedPath] = []
    while index < len(fields) and fields[index]:
        status = fields[index].decode("ascii")
        index += 1
        if status.startswith(("R", "C")):
            old_path = fields[index].decode("utf-8")
            new_path = fields[index + 1].decode("utf-8")
            index += 2
            result.append(VerificationChangedPath(new_path, ChangeKind.RENAMED, old_path))
            continue
        path = fields[index].decode("utf-8")
        index += 1
        kind = {"A": ChangeKind.ADDED, "D": ChangeKind.DELETED}.get(status[0], ChangeKind.MODIFIED)
        result.append(VerificationChangedPath(path, kind))
    return tuple(result)


def _git(*args: str) -> str:
    return _git_bytes(*args).decode("utf-8")


def _git_bytes(*args: str) -> bytes:
    try:
        process = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    except OSError as exc:
        raise ValueError(f"unable to execute git: {exc}") from exc
    if process.returncode:
        diagnostic = process.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {diagnostic}")
    return process.stdout


def verification_commands(plan: VerificationPlan) -> list[tuple[str, tuple[str, ...]]]:
    if (
        plan.impact.escalation >= VerificationEscalation.BROAD
        or bool({OnlyTestLane.CORE_FULL, OnlyTestLane.FAST, OnlyTestLane.INTEGRATION}.intersection(plan.impact.lanes))
        or OnlyReleaseCheck.BUILD in plan.impact.checks
        or {OnlyReleaseCheck.WEB_UNIT, OnlyReleaseCheck.WEB_BUILD, OnlyReleaseCheck.WEB_E2E}.issubset(
            plan.impact.checks
        )
        or any(
            reason.rule == "manual-impact-review-required"
            or reason.path in {"pyproject.toml", "uv.lock", "Cargo.toml", "Cargo.lock", "rust-toolchain.toml"}
            for reason in plan.impact.reasons
        )
    ):
        unbounded = ", ".join(sorted({reason.path for reason in plan.impact.reasons}))
        raise ValueError(
            "LOCAL_IMPACT_REVIEW_REQUIRED: bounded automatic checks unavailable for "
            + unbounded
            + "; select affected module checks explicitly through the canonical dev entry"
        )
    commands: list[tuple[str, tuple[str, ...]]] = []
    for check in plan.impact.checks:
        if check is OnlyReleaseCheck.RUST_KERNEL:
            from scripts.rust_kernel_check import affected_packages

            paths = tuple(sorted({reason.path for reason in plan.impact.reasons if reason.rule == "rust-kernel"}))
            try:
                packages = affected_packages(ROOT, paths)
            except ValueError as exc:
                raise ValueError(f"LOCAL_IMPACT_REVIEW_REQUIRED: {exc}") from exc
            arguments = tuple(flag for package in packages for flag in ("--package", package))
            commands.append(
                (
                    "check:rust-selected",
                    ("uv", "run", "python", "scripts/rust_kernel_check.py", *(arguments or ("--source-check",))),
                )
            )
            tool_tests: set[str] = set()
            for path in paths:
                if path.startswith("scripts/tests/") and path.endswith(".py") and (ROOT / path).is_file():
                    tool_tests.add(path)
                if path.startswith("scripts/"):
                    stem = Path(path).stem
                    script_tests = {
                        str(test.relative_to(ROOT)) for test in (ROOT / "scripts/tests").glob(f"test_{stem}*.py")
                    }
                    if stem.endswith("_reference_check"):
                        test = f"scripts/tests/test_rust_{stem.removesuffix('_reference_check')}_boundary.py"
                        if (ROOT / test).is_file():
                            script_tests.add(test)
                    if not script_tests:
                        raise ValueError(
                            f"LOCAL_IMPACT_REVIEW_REQUIRED: owning tool/protocol tests are unmapped for {path}"
                        )
                    tool_tests.update(script_tests)
            if tool_tests:
                commands.append(
                    ("check:rust-tools", ("uv", "run", "python", "-m", "pytest", "-q", *sorted(tool_tests)))
                )
            continue
        if check is not OnlyReleaseCheck.BUILD:
            if (
                check is OnlyReleaseCheck.STATIC
                and plan.impact.escalation is VerificationEscalation.COMPONENT
                and plan.impact.static_plan is not None
            ):
                _append_scoped_static_commands(commands, plan.impact.static_plan)
            else:
                _append_check_commands(commands, check)
    if plan.impact.escalation is not VerificationEscalation.COMPONENT:
        _append_distribution_commands(commands, plan.impact.static_plan)
    for lane in plan.impact.lanes:
        commands.append((f"lane:{lane.value}", ("uv", "run", "python", "scripts/test_suite.py", lane.value)))
    if OnlyReleaseCheck.BUILD in plan.impact.checks:
        _append_check_commands(commands, OnlyReleaseCheck.BUILD)
    return commands


def _append_scoped_static_commands(
    commands: list[tuple[str, tuple[str, ...]]], static_plan: VerificationStaticPlan | None
) -> None:
    if static_plan is None:
        return
    if static_plan.ruff_targets:
        commands.append(("check:affected-ruff", ("uv", "run", "ruff", "check", *static_plan.ruff_targets)))
    if static_plan.format_targets:
        commands.append(
            ("check:affected-format", ("uv", "run", "ruff", "format", "--check", *static_plan.format_targets))
        )
    if static_plan.mypy_targets:
        commands.append(("check:affected-mypy", ("uv", "run", "mypy", *static_plan.mypy_targets)))
    if static_plan.import_linter_required:
        commands.append(("check:import-linter", ("uv", "run", "lint-imports")))
    if static_plan.version_sync_required:
        commands.append(("check:version-sync", ("uv", "run", "python", "scripts/version_sync.py", "check")))
    for package in static_plan.build_targets:
        commands.append((f"check:build-{package}", ("uv", "build", "--package", package)))


def _append_distribution_commands(
    commands: list[tuple[str, tuple[str, ...]]], static_plan: VerificationStaticPlan | None
) -> None:
    if static_plan is None:
        return
    if static_plan.version_sync_required:
        commands.append(("check:version-sync", ("uv", "run", "python", "scripts/version_sync.py", "check")))
    for package in static_plan.build_targets:
        commands.append((f"check:build-{package}", ("uv", "build", "--package", package)))


def _append_check_commands(commands: list[tuple[str, tuple[str, ...]]], check: OnlyReleaseCheck) -> None:
    check_commands = release_check_commands(check)
    for index, command in enumerate(check_commands, start=1):
        suffix = "" if len(check_commands) == 1 else f"-{index:02d}"
        commands.append((f"check:{check.value}{suffix}", command))


def run_plan(plan: VerificationPlan, *, verbose: bool = False) -> int:
    commands = verification_commands(plan)
    if not commands:
        if plan.change_set.changed_paths:
            print("No executable checks selected for the current change set.")
            print("Use AGENTS.md and the Task Contract to confirm whether additional Impact Scope proof is required.")
        else:
            print("No staged, unstaged, or untracked working-tree changes detected.")
        return 0

    results: list[VerificationStepResult] = []
    for gate, command in commands:
        result = _run_step(gate, command, verbose=verbose)
        results.append(result)
        _print_result(result)
        if result.exit_code:
            break

    passed = len(results) == len(commands) and all(result.exit_code == 0 for result in results)
    print()
    print("SELECTED CHECKS PASSED" if passed else "SELECTED CHECKS FAILED")
    print(f"{len(results)} checks executed; no verification evidence was persisted")
    return 0 if passed else 1


def _run_step(gate: str, command: tuple[str, ...], *, verbose: bool) -> VerificationStepResult:
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
        output = process.stdout + process.stderr
        exit_code = process.returncode
    except OSError as exc:
        output = f"runner failure: {exc}\n"
        exit_code = 127

    if verbose and output:
        print(output, end="" if output.endswith("\n") else "\n")
    return VerificationStepResult(
        gate=gate,
        command=command,
        exit_code=exit_code,
        duration_seconds=round(time.monotonic() - started, 6),
        output=output,
        collected=_collected_count(output),
    )


def _print_result(result: VerificationStepResult) -> None:
    status = "PASS" if result.exit_code == 0 else "FAIL"
    collected = "" if result.collected is None else f"  {result.collected} collected"
    print(f"{status} {result.gate:<30} {result.duration_seconds:7.2f}s{collected}")
    if result.exit_code:
        print(f"exit_code={result.exit_code}")
        print(f"command: {shlex.join(result.command)}")
        print("diagnostic:")
        print("\n".join(result.output.splitlines()[-60:]))


def _collected_count(content: str) -> int | None:
    match = re.search(r"Lane [^:]+: (\d+) collected", content)
    return None if match is None else int(match.group(1))


def _print_plan(plan: VerificationPlan, output: TextIO = sys.stdout) -> None:
    json.dump(plan.as_json(), output, indent=2, sort_keys=True)
    output.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select or run impact-aware checks for current working-tree changes; never a task-completion authority"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    try:
        plan = plan_for_change_set(resolve_change_set())
    except ValueError as exc:
        print(f"PLAN_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.command == "plan":
        _print_plan(plan)
        return 0
    try:
        return run_plan(plan, verbose=args.verbose)
    except ValueError as exc:
        print(f"PLAN_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
