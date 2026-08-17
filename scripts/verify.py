from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.test_suite import RELEASE_LANES, OnlyReleaseCheck, OnlyTestLane, release_check_commands  # noqa: E402

LOG_ROOT = ROOT / "test-results" / "verification"


class VerificationEscalation(IntEnum):
    DOCS_ONLY = 0
    COMPONENT = 1
    BROAD = 2
    FULL_LOCAL = 3
    VERIFICATION_INFRASTRUCTURE = 4


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
    base_revision: str
    head_revision: str
    changed_paths: tuple[VerificationChangedPath, ...]
    dirty_worktree: bool

    def as_json(self) -> dict[str, object]:
        return {
            "base_revision": self.base_revision,
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
class VerificationPlan:
    change_set: VerificationChangeSet
    impact: VerificationImpact

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "authority": "LOCAL_DEVELOPMENT_VERIFICATION_ONLY",
            "change_set": self.change_set.as_json(),
            "impact": self.impact.as_json(),
        }


@dataclass(frozen=True, slots=True)
class VerificationStepResult:
    gate: str
    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float
    log_path: str
    collected: int | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "gate": self.gate,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "log_path": self.log_path,
            "collected": self.collected,
        }


STATIC = (OnlyReleaseCheck.STATIC,)
WEB_CHECKS = (
    OnlyReleaseCheck.WEB_STATIC,
    OnlyReleaseCheck.WEB_UNIT,
    OnlyReleaseCheck.WEB_BUILD,
    OnlyReleaseCheck.WEB_E2E,
)
FULL_CHECKS = tuple(OnlyReleaseCheck)
RESEARCH_CHAIN = (
    OnlyTestLane.RESEARCH_RUNTIME,
    OnlyTestLane.RESEARCH_CALCULATION,
    OnlyTestLane.RESEARCH_FACTOR,
    OnlyTestLane.RESEARCH_EVALUATION,
    OnlyTestLane.RESEARCH_JOB,
    OnlyTestLane.RESEARCH_SWEEP,
    OnlyTestLane.RESEARCH_RESULT,
    OnlyTestLane.RESEARCH_ARTIFACT,
    OnlyTestLane.RESEARCH_QUERY,
)
CORE_RECOVERY = (OnlyTestLane.CORE_FULL, OnlyTestLane.RECOVERY, OnlyTestLane.SIM_RECOVERY)

IMPACT_RULES = (
    VerificationImpactRule(
        "research-web",
        ("apps/onlyalpha-web/",),
        (),
        (),
        WEB_CHECKS,
        VerificationEscalation.COMPONENT,
        "Web is a read-only consumer whose impact stops at the Research API contract boundary",
    ),
    VerificationImpactRule(
        "research-api-web-contract",
        ("packages/api/onlyalpha-api/", "contracts/research-api/v2/"),
        ("scripts/export_research_openapi.py",),
        (),
        WEB_CHECKS,
        VerificationEscalation.COMPONENT,
        "HTTP transport changes require generated contract and browser-consumer verification",
    ),
    VerificationImpactRule(
        "research-runtime",
        ("src/onlyalpha/runtime/research/", "tests/runtime/research/"),
        ("src/onlyalpha/runtime/product.py", "tests/architecture/test_research_runtime_boundaries.py"),
        (OnlyTestLane.RESEARCH_RUNTIME,),
        STATIC,
        VerificationEscalation.COMPONENT,
        "finite Research Runtime orchestrates existing immutable Research authorities",
    ),
    VerificationImpactRule(
        "research-query",
        (
            "src/onlyalpha/research/query/",
            "tests/research/query/",
            "packages/api/onlyalpha-api/",
        ),
        ("tests/architecture/test_research_query_boundaries.py",),
        (OnlyTestLane.RESEARCH_QUERY, OnlyTestLane.RESEARCH_ARTIFACT),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Query owns the read-only consumer projection and API boundary",
    ),
    VerificationImpactRule(
        "research-artifact",
        ("src/onlyalpha/research/artifact/", "tests/research/artifact/"),
        ("tests/architecture/test_research_artifact_boundaries.py",),
        (OnlyTestLane.RESEARCH_RUNTIME, OnlyTestLane.RESEARCH_QUERY, OnlyTestLane.RESEARCH_ARTIFACT),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Artifact owns the derived immutable portable read boundary",
    ),
    VerificationImpactRule(
        "research-result",
        ("src/onlyalpha/research/result/", "tests/research/result/"),
        ("tests/architecture/test_research_result_boundaries.py",),
        (
            OnlyTestLane.RESEARCH_RUNTIME,
            OnlyTestLane.RESEARCH_QUERY,
            OnlyTestLane.RESEARCH_RESULT,
            OnlyTestLane.RESEARCH_ARTIFACT,
        ),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Result owns deterministic composition and immutable output authority",
    ),
    VerificationImpactRule(
        "research-evaluation",
        (
            "src/onlyalpha/research/evaluation/",
            "tests/research/evaluation/",
            "packages/target/onlyalpha-plugin-targets/",
        ),
        ("tests/architecture/test_research_evaluation_boundaries.py",),
        (
            OnlyTestLane.RESEARCH_RUNTIME,
            OnlyTestLane.RESEARCH_QUERY,
            OnlyTestLane.RESEARCH_EVALUATION,
            OnlyTestLane.RESEARCH_RESULT,
            OnlyTestLane.RESEARCH_ARTIFACT,
        ),
        STATIC,
        VerificationEscalation.COMPONENT,
        "evaluation owns Target, Statistics identity, alignment, and immutable result verification",
    ),
    VerificationImpactRule(
        "research-sweep",
        ("src/onlyalpha/research/sweep/", "tests/research/sweep/"),
        ("tests/architecture/test_research_sweep_boundaries.py",),
        (OnlyTestLane.RESEARCH_RUNTIME, OnlyTestLane.RESEARCH_SWEEP, OnlyTestLane.RESEARCH_JOB),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Sweep composition delegates execution to immutable Research Jobs",
    ),
    VerificationImpactRule(
        "verification-infrastructure",
        ("scripts/pytest_", "tests/architecture/test_agent_verification", ".github/workflows/"),
        (
            "scripts/test_suite.py",
            "scripts/certification.py",
            "scripts/verify.py",
            "scripts/web_suite.py",
            "tests/conftest.py",
            "tests/architecture/test_test_lane_contract.py",
            "tests/architecture/test_certification_contract.py",
        ),
        RELEASE_LANES,
        FULL_CHECKS,
        VerificationEscalation.VERIFICATION_INFRASTRUCTURE,
        "verification tooling cannot narrow its own local proof boundary",
    ),
    VerificationImpactRule(
        "package-metadata",
        (),
        ("pyproject.toml", "uv.lock", "packages/api/onlyalpha-api/pyproject.toml"),
        (),
        STATIC,
        VerificationEscalation.COMPONENT,
        "package metadata requires version synchronization and a targeted root package build",
    ),
    VerificationImpactRule(
        "research-dataset",
        ("src/onlyalpha/research/dataset/", "tests/research/dataset/"),
        ("src/onlyalpha/research/dataset.py",),
        (OnlyTestLane.RESEARCH_DATASET, *RESEARCH_CHAIN),
        STATIC,
        VerificationEscalation.COMPONENT,
        "dataset identity and admission feed calculation, factor, and job authorities",
    ),
    VerificationImpactRule(
        "research-calculation",
        ("src/onlyalpha/research/calculation/", "tests/research/calculation/"),
        (),
        RESEARCH_CHAIN,
        STATIC,
        VerificationEscalation.COMPONENT,
        "research calculation is upstream of factor execution and job orchestration",
    ),
    VerificationImpactRule(
        "research-factor",
        ("tests/research/factor/", "packages/factor/onlyalpha-plugin-factors/"),
        (),
        (
            OnlyTestLane.RESEARCH_RUNTIME,
            OnlyTestLane.RESEARCH_FACTOR,
            OnlyTestLane.RESEARCH_JOB,
            OnlyTestLane.RESEARCH_SWEEP,
        ),
        STATIC,
        VerificationEscalation.COMPONENT,
        "factor semantics are consumed by immutable research jobs",
    ),
    VerificationImpactRule(
        "research-job",
        ("src/onlyalpha/research/job/", "tests/research/job/"),
        (),
        (OnlyTestLane.RESEARCH_RUNTIME, OnlyTestLane.RESEARCH_JOB, OnlyTestLane.RESEARCH_SWEEP),
        STATIC,
        VerificationEscalation.COMPONENT,
        "research job changes are covered by the canonical job application lane",
    ),
    VerificationImpactRule(
        "calculation-foundation",
        ("src/onlyalpha/calculation/", "tests/calculation/", "packages/indicator/onlyalpha-plugin-indicators/"),
        (),
        (OnlyTestLane.CALCULATION, *RESEARCH_CHAIN, OnlyTestLane.CORE_FULL),
        STATIC,
        VerificationEscalation.BROAD,
        "calculation definitions and official backends cross research and trading consumers",
    ),
    VerificationImpactRule(
        "streaming-recovery",
        ("src/onlyalpha/runtime/streaming/", "src/onlyalpha/runtime/sim/", "tests/runtime/streaming/"),
        (),
        CORE_RECOVERY,
        STATIC,
        VerificationEscalation.BROAD,
        "streaming changes affect core behavior and both recovery contracts",
    ),
    VerificationImpactRule(
        "shared-trading-core",
        (
            "src/onlyalpha/domain/",
            "src/onlyalpha/execution/",
            "src/onlyalpha/order/",
            "src/onlyalpha/account/",
            "src/onlyalpha/position/",
            "src/onlyalpha/runtime/",
            "src/onlyalpha/recovery/",
            "src/onlyalpha/checkpoint/",
        ),
        (),
        CORE_RECOVERY,
        STATIC,
        VerificationEscalation.BROAD,
        "shared trading authorities require core and forward-recovery verification",
    ),
    VerificationImpactRule(
        "cn-ashare-market",
        ("packages/market/onlyalpha-market-cn-ashare/", "tests/conformance/cn_a_share_cash/"),
        (),
        (OnlyTestLane.ASHARE, OnlyTestLane.CORE_FULL, OnlyTestLane.RECOVERY),
        STATIC,
        VerificationEscalation.BROAD,
        "versioned A-share market semantics feed durable core execution",
    ),
    VerificationImpactRule(
        "generic-market",
        ("packages/market/onlyalpha-market-generic-t0-cash/",),
        (),
        (OnlyTestLane.CORE_FULL, OnlyTestLane.RECOVERY, OnlyTestLane.SIM_RECOVERY),
        STATIC,
        VerificationEscalation.BROAD,
        "the generic market product is shared by current Backtest and SIM durable paths",
    ),
    VerificationImpactRule(
        "miniqmt-provider",
        ("packages/provider/onlyalpha-plugin-miniqmt/",),
        (),
        (OnlyTestLane.MINIQMT_CONTRACT, OnlyTestLane.RESEARCH_DATASET),
        STATIC,
        VerificationEscalation.COMPONENT,
        "MiniQMT contract and historical Dataset admission are directly affected",
    ),
    VerificationImpactRule(
        "tushare-provider",
        ("packages/provider/onlyalpha-plugin-tushare/",),
        (),
        (OnlyTestLane.RESEARCH_DATASET,),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Tushare historical normalization feeds Dataset materialization",
    ),
    VerificationImpactRule(
        "shared-test-infrastructure",
        ("tests/fixtures/", "tests/support/", "tests/architecture/"),
        (),
        RELEASE_LANES,
        FULL_CHECKS,
        VerificationEscalation.FULL_LOCAL,
        "shared fixtures, support, and architecture gates can affect every canonical lane",
        (
            "tests/architecture/test_research_result_boundaries.py",
            "tests/architecture/test_research_query_boundaries.py",
        ),
    ),
    VerificationImpactRule(
        "docs-only",
        ("docs/", "prompts/"),
        ("README.md", "AGENTS.md"),
        (),
        (),
        VerificationEscalation.DOCS_ONLY,
        "documentation and implementation prompts do not change executable Runtime semantics",
    ),
)


def plan_for_change_set(change_set: VerificationChangeSet) -> VerificationPlan:
    change_set = VerificationChangeSet(
        change_set.base_revision,
        change_set.head_revision,
        tuple(sorted(change_set.changed_paths, key=lambda item: (item.path, item.kind.value, item.old_path or ""))),
        change_set.dirty_worktree,
    )
    lane_set: set[OnlyTestLane] = set()
    check_set: set[OnlyReleaseCheck] = set()
    reasons: list[ImpactReason] = []
    escalation = VerificationEscalation.DOCS_ONLY
    for changed in sorted(change_set.changed_paths, key=lambda item: (item.path, item.kind.value, item.old_path or "")):
        for path in changed.impact_paths():
            matched = tuple(rule for rule in IMPACT_RULES if rule.matches(path))
            if not matched:
                matched = (_unknown_rule(path),)
            for rule in matched:
                lane_set.update(rule.lanes)
                check_set.update(rule.checks)
                escalation = max(escalation, rule.escalation)
                reasons.append(ImpactReason(path, rule.name, rule.rationale))
    lanes = tuple(lane for lane in RELEASE_LANES if lane in lane_set)
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
        "unknown-impact-fallback",
        (),
        (path,),
        RELEASE_LANES,
        FULL_CHECKS,
        VerificationEscalation.FULL_LOCAL,
        "unclassified path fails closed to the complete local release gate set",
    )


def _static_plan(
    change_set: VerificationChangeSet,
    rule_names: tuple[str, ...],
    escalation: VerificationEscalation,
) -> VerificationStaticPlan | None:
    if escalation is VerificationEscalation.DOCS_ONLY:
        return None
    if escalation >= VerificationEscalation.FULL_LOCAL:
        return VerificationStaticPlan()
    changed_python = tuple(
        sorted(
            {
                path
                for changed in change_set.changed_paths
                for path in changed.impact_paths()
                if path.endswith(".py") and changed.kind is not ChangeKind.DELETED
            }
        )
    )
    rules = set(rule_names)
    typed_roots = {
        "research-runtime": ("src/onlyalpha/runtime/research", "src/onlyalpha/runtime/product.py"),
        "research-artifact": ("src/onlyalpha/research/artifact",),
        "research-query": (
            "src/onlyalpha/research/query",
            "packages/api/onlyalpha-api/src/onlyalpha_api",
        ),
        "research-result": ("src/onlyalpha/research/result",),
        "research-evaluation": ("src/onlyalpha/research/evaluation", "src/onlyalpha/research/result"),
        "research-sweep": ("src/onlyalpha/research/sweep",),
        "research-job": ("src/onlyalpha/research/job",),
        "research-calculation": ("src/onlyalpha/research/calculation",),
        "research-dataset": ("src/onlyalpha/research/dataset",),
    }
    mypy_targets = tuple(sorted({target for rule in rules for target in typed_roots.get(rule, ())}))
    architecture = any(
        path.startswith("tests/architecture/")
        for changed in change_set.changed_paths
        for path in changed.impact_paths()
    )
    return VerificationStaticPlan(
        changed_python,
        changed_python,
        mypy_targets,
        architecture,
        "package-metadata" in rules,
        tuple(
            sorted(
                {
                    *(("onlyalpha-api",) if "research-query" in rules else ()),
                    *(("onlyalpha",) if "package-metadata" in rules else ()),
                }
            )
        ),
    )


def resolve_change_set(base: str) -> VerificationChangeSet:
    base_revision = _git("rev-parse", "--verify", f"{base}^{{commit}}").strip()
    head_revision = _git("rev-parse", "HEAD").strip()
    changes: dict[tuple[str, str | None], VerificationChangedPath] = {}
    for args in (
        ("diff", "--name-status", "-z", "--find-renames", base_revision, head_revision),
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
        base_revision,
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


def run_plan(plan: VerificationPlan, *, verbose: bool = False) -> int:
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{plan.change_set.head_revision[:12]}-{os.getpid()}"
    log_root = LOG_ROOT / run_id
    log_root.mkdir(parents=True, exist_ok=False)
    _write_json(log_root / "plan.json", plan.as_json())
    results: list[VerificationStepResult] = []
    commands = verification_commands(plan)
    for gate, command in commands:
        result = _run_step(gate, command, log_root, verbose=verbose)
        results.append(result)
        _print_result(result, log_root)
        if result.exit_code:
            break
    passed = len(results) == len(commands) and all(result.exit_code == 0 for result in results)
    manifest = {
        "schema_version": 1,
        "authority": "LOCAL_DEVELOPMENT_VERIFICATION_ONLY",
        "verification_id": run_id,
        "plan": plan.as_json(),
        "commands": [{"gate": gate, "command": list(command)} for gate, command in commands],
        "results": [result.as_json() for result in results],
        "result": "VERIFICATION_PASSED" if passed else "VERIFICATION_FAILED",
    }
    _write_json(log_root / "manifest.json", manifest)
    print()
    print("IMPACT VERIFIED" if passed else "IMPACT VERIFICATION FAILED")
    print(f"{len(results)} gates executed")
    print(f"full logs: {log_root.relative_to(ROOT)}/")
    return 0 if passed else 1


def verification_commands(plan: VerificationPlan) -> list[tuple[str, tuple[str, ...]]]:
    commands: list[tuple[str, tuple[str, ...]]] = []
    for check in plan.impact.checks:
        if check is not OnlyReleaseCheck.BUILD:
            if (
                check is OnlyReleaseCheck.STATIC
                and plan.impact.escalation is VerificationEscalation.COMPONENT
                and plan.impact.static_plan is not None
            ):
                _append_scoped_static_commands(commands, plan.impact.static_plan)
            else:
                _append_check_commands(commands, check)
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


def _append_check_commands(commands: list[tuple[str, tuple[str, ...]]], check: OnlyReleaseCheck) -> None:
    check_commands = release_check_commands(check)
    for index, command in enumerate(check_commands, start=1):
        suffix = "" if len(check_commands) == 1 else f"-{index:02d}"
        commands.append((f"check:{check.value}{suffix}", command))


def _run_step(gate: str, command: tuple[str, ...], log_root: Path, *, verbose: bool) -> VerificationStepResult:
    log_path = log_root / f"{_safe_gate_name(gate)}.log"
    started = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8") as output:
            output.write(f"cwd: {ROOT}\ncommand: {shlex.join(command)}\n\n")
            output.flush()
            process = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=False, text=True)
    except OSError as exc:
        try:
            log_path.write_text(f"runner failure: {exc}\n", encoding="utf-8")
        except OSError as log_exc:
            print(f"unable to persist verification failure log: {log_exc}", file=sys.stderr)
        return VerificationStepResult(gate, command, 127, time.monotonic() - started, str(log_path))
    content = log_path.read_text(encoding="utf-8", errors="replace")
    if verbose:
        print(content, end="" if content.endswith("\n") else "\n")
    collected = _collected_count(content)
    return VerificationStepResult(
        gate,
        command,
        process.returncode,
        round(time.monotonic() - started, 6),
        str(log_path.relative_to(ROOT)),
        collected,
    )


def _print_result(result: VerificationStepResult, log_root: Path) -> None:
    status = "PASS" if result.exit_code == 0 else "FAIL"
    collected = "" if result.collected is None else f"  {result.collected} collected"
    print(f"{status} {result.gate:<30} {result.duration_seconds:7.2f}s{collected}")
    if result.exit_code:
        print(f"exit_code={result.exit_code}")
        print(f"command: {shlex.join(result.command)}")
        print("diagnostic:")
        log_path = ROOT / result.log_path
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-60:]))
        print(f"full log: {log_path.relative_to(ROOT)}")


def _collected_count(content: str) -> int | None:
    match = re.search(r"Lane [^:]+: (\d+) collected", content)
    return None if match is None else int(match.group(1))


def _safe_gate_name(gate: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", gate)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _print_plan(plan: VerificationPlan, output: TextIO = sys.stdout) -> None:
    json.dump(plan.as_json(), output, indent=2, sort_keys=True)
    output.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Conservative local development verification; never certification authority"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "agent"):
        child = subparsers.add_parser(command)
        child.add_argument("--base", required=True, help="explicit commit used as the change-set base")
        if command == "agent":
            child.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    try:
        plan = plan_for_change_set(resolve_change_set(args.base))
    except ValueError as exc:
        print(f"PLAN_ERROR: {exc}", file=sys.stderr)
        return 2
    if args.command == "plan":
        _print_plan(plan)
        return 0
    return run_plan(plan, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
