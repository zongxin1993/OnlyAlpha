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
RESEARCH_CHAIN = (
    OnlyTestLane.RESEARCH_RUN,
    OnlyTestLane.RESEARCH_COMMAND,
    OnlyTestLane.RESEARCH_EXECUTION,
    OnlyTestLane.RESEARCH_POSTGRES,
    OnlyTestLane.RESEARCH_RUNTIME,
    OnlyTestLane.RESEARCH_CALCULATION,
    OnlyTestLane.RESEARCH_DEFINITION,
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
        "quality-infrastructure",
        (".github/workflows/", "scripts/pytest_"),
        (
            "AGENTS.md",
            "quality-policy.toml",
            "scripts/test_suite.py",
            "scripts/quality_policy.py",
            "scripts/dependency_audit.py",
            "scripts/verify.py",
            "scripts/web_suite.py",
            "tests/conftest.py",
            "tests/architecture/test_test_lane_contract.py",
            "tests/architecture/test_quality_policy_contract.py",
            "tests/architecture/test_dependency_audit_contract.py",
            "tests/architecture/test_task_acceptance_policy.py",
        ),
        (OnlyTestLane.ARCHITECTURE,),
        STATIC,
        VerificationEscalation.QUALITY_INFRASTRUCTURE,
        "quality infrastructure requires its architecture contracts and static consistency checks",
    ),
    VerificationImpactRule(
        "research-definition",
        ("src/onlyalpha/research/definition/", "tests/research/definition/"),
        ("tests/architecture/test_research_definition_boundaries.py",),
        (
            OnlyTestLane.RESEARCH_DEFINITION,
            OnlyTestLane.RESEARCH_SPECIFICATION,
            OnlyTestLane.RESEARCH_SWEEP,
            OnlyTestLane.RESEARCH_CALCULATION,
        ),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Definition owns normalized authoring intent and deterministic Specification lowering",
    ),
    VerificationImpactRule(
        "research-run",
        ("src/onlyalpha/research/run/", "tests/research/run/"),
        ("src/onlyalpha/research/__init__.py", "tests/architecture/test_research_run_boundaries.py"),
        (
            OnlyTestLane.RESEARCH_RUN,
            OnlyTestLane.RESEARCH_COMMAND,
            OnlyTestLane.RESEARCH_EXECUTION,
            OnlyTestLane.RESEARCH_POSTGRES,
        ),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Run owns durable operational identity, admission and transitions",
    ),
    VerificationImpactRule(
        "research-command",
        ("src/onlyalpha/research/command/", "tests/research/command/"),
        ("tests/architecture/test_research_command_boundaries.py",),
        (OnlyTestLane.RESEARCH_COMMAND, OnlyTestLane.RESEARCH_RUN, OnlyTestLane.RESEARCH_POSTGRES),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Command owns submission idempotency and cancellation interpretation",
    ),
    VerificationImpactRule(
        "research-execution",
        ("src/onlyalpha/research/execution/", "tests/research/execution/"),
        ("tests/architecture/test_research_execution_boundaries.py",),
        (OnlyTestLane.RESEARCH_EXECUTION, OnlyTestLane.RESEARCH_POSTGRES),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Execution owns scheduler, worker, lease and operational recovery",
    ),
    VerificationImpactRule(
        "research-postgres",
        ("src/onlyalpha/persistence/postgres/", "tests/research/postgres/", "database/postgres/migrations/"),
        (
            "src/onlyalpha/persistence/__init__.py",
            "scripts/database.py",
            "tests/architecture/test_postgres_operational_authority.py",
        ),
        (OnlyTestLane.RESEARCH_COMMAND, OnlyTestLane.RESEARCH_EXECUTION, OnlyTestLane.RESEARCH_POSTGRES),
        STATIC,
        VerificationEscalation.BROAD,
        "PostgreSQL persistence and migrations require operational and schema-impact proof",
    ),
    VerificationImpactRule(
        "research-web",
        ("apps/onlyalpha-web/",),
        (),
        (),
        WEB_CHECKS,
        VerificationEscalation.COMPONENT,
        "Web impact stops at the Research API consumer boundary",
    ),
    VerificationImpactRule(
        "research-api-web-contract",
        ("packages/api/onlyalpha-api/", "contracts/research-api/v2/", "tests/contracts/"),
        (
            "scripts/export_research_openapi.py",
            "scripts/openapi_contract.py",
            "tests/architecture/test_p9_k4_openapi_governance.py",
        ),
        (OnlyTestLane.RESEARCH_QUERY, OnlyTestLane.RESEARCH_COMMAND),
        WEB_CHECKS,
        VerificationEscalation.BROAD,
        "HTTP public contract changes require producer and browser-consumer verification",
    ),
    VerificationImpactRule(
        "research-runtime",
        ("src/onlyalpha/runtime/research/", "tests/runtime/research/"),
        ("src/onlyalpha/runtime/product.py", "tests/architecture/test_research_runtime_boundaries.py"),
        (OnlyTestLane.RESEARCH_EXECUTION, OnlyTestLane.RESEARCH_RUNTIME),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Runtime orchestrates immutable Research authorities",
    ),
    VerificationImpactRule(
        "research-specification",
        ("src/onlyalpha/research/specification/", "tests/research/specification/"),
        ("tests/architecture/test_research_specification_boundaries.py",),
        (OnlyTestLane.RESEARCH_SPECIFICATION, OnlyTestLane.RESEARCH_RUN, OnlyTestLane.RESEARCH_EXECUTION),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Specification owns request admission and deterministic workload compilation",
    ),
    VerificationImpactRule(
        "research-workload",
        (),
        ("src/onlyalpha/research/workload.py",),
        (OnlyTestLane.RESEARCH_SPECIFICATION, OnlyTestLane.RESEARCH_EXECUTION, OnlyTestLane.RESEARCH_RUNTIME),
        STATIC,
        VerificationEscalation.COMPONENT,
        "WorkloadPlan is shared by Specification compilation and Research Runtime",
    ),
    VerificationImpactRule(
        "research-query",
        ("src/onlyalpha/research/query/", "tests/research/query/", "packages/api/onlyalpha-api/"),
        ("tests/architecture/test_research_query_boundaries.py",),
        (OnlyTestLane.RESEARCH_QUERY, OnlyTestLane.RESEARCH_ARTIFACT),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Query owns the read-only consumer projection",
    ),
    VerificationImpactRule(
        "research-artifact",
        ("src/onlyalpha/research/artifact/", "tests/research/artifact/"),
        ("tests/architecture/test_research_artifact_boundaries.py",),
        (OnlyTestLane.RESEARCH_RUNTIME, OnlyTestLane.RESEARCH_QUERY, OnlyTestLane.RESEARCH_ARTIFACT),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Artifact owns the immutable portable read boundary",
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
        "research-result-plan-specification-contract",
        (),
        ("src/onlyalpha/research/result/plan.py",),
        (OnlyTestLane.RESEARCH_SPECIFICATION,),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Result Plan composition is a direct Specification output",
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
        "Evaluation owns Target/Statistics identity and immutable result verification",
    ),
    VerificationImpactRule(
        "research-evaluation-specification-contract",
        (),
        (
            "src/onlyalpha/research/evaluation/definition.py",
            "src/onlyalpha/research/evaluation/plan.py",
            "src/onlyalpha/research/evaluation/reference.py",
        ),
        (OnlyTestLane.RESEARCH_SPECIFICATION,),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Evaluation definitions and references are direct Specification outputs",
    ),
    VerificationImpactRule(
        "research-sweep",
        ("src/onlyalpha/research/sweep/", "tests/research/sweep/"),
        ("tests/architecture/test_research_sweep_boundaries.py",),
        (
            OnlyTestLane.RESEARCH_SPECIFICATION,
            OnlyTestLane.RESEARCH_RUNTIME,
            OnlyTestLane.RESEARCH_SWEEP,
            OnlyTestLane.RESEARCH_JOB,
        ),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Sweep composition delegates execution to immutable Research Jobs",
    ),
    VerificationImpactRule(
        "research-dataset-specification-contract",
        (),
        ("src/onlyalpha/research/dataset/strict.py", "src/onlyalpha/research/dataset/manifest.py"),
        (OnlyTestLane.RESEARCH_SPECIFICATION,),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Dataset identity and admission are direct Specification contracts",
    ),
    VerificationImpactRule(
        "research-dataset",
        ("src/onlyalpha/research/dataset/", "tests/research/dataset/"),
        ("src/onlyalpha/research/dataset.py",),
        (OnlyTestLane.RESEARCH_DATASET, *RESEARCH_CHAIN),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Dataset identity and admission feed downstream Research authorities",
    ),
    VerificationImpactRule(
        "research-calculation",
        ("src/onlyalpha/research/calculation/", "tests/research/calculation/"),
        (),
        (OnlyTestLane.RESEARCH_SPECIFICATION, *RESEARCH_CHAIN),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research calculation is upstream of factor execution and jobs",
    ),
    VerificationImpactRule(
        "research-factor",
        ("tests/research/factor/", "packages/factor/onlyalpha-plugin-factors/"),
        (),
        (
            OnlyTestLane.RESEARCH_SPECIFICATION,
            OnlyTestLane.RESEARCH_RUNTIME,
            OnlyTestLane.RESEARCH_FACTOR,
            OnlyTestLane.RESEARCH_JOB,
            OnlyTestLane.RESEARCH_SWEEP,
        ),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Factor semantics are consumed by immutable Research Jobs",
    ),
    VerificationImpactRule(
        "research-job",
        ("src/onlyalpha/research/job/", "tests/research/job/"),
        (),
        (
            OnlyTestLane.RESEARCH_SPECIFICATION,
            OnlyTestLane.RESEARCH_RUNTIME,
            OnlyTestLane.RESEARCH_JOB,
            OnlyTestLane.RESEARCH_SWEEP,
        ),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Research Job changes use the canonical job application lane",
    ),
    VerificationImpactRule(
        "calculation-foundation",
        ("src/onlyalpha/calculation/", "tests/calculation/", "packages/indicator/onlyalpha-plugin-indicators/"),
        (),
        (OnlyTestLane.RESEARCH_SPECIFICATION, OnlyTestLane.CALCULATION, *RESEARCH_CHAIN, OnlyTestLane.CORE_FULL),
        STATIC,
        VerificationEscalation.BROAD,
        "Calculation definitions and official backends cross Research and Trading consumers",
    ),
    VerificationImpactRule(
        "streaming-recovery",
        ("src/onlyalpha/runtime/streaming/", "src/onlyalpha/runtime/sim/", "tests/runtime/streaming/"),
        (),
        CORE_RECOVERY,
        STATIC,
        VerificationEscalation.BROAD,
        "Streaming changes affect core behavior and recovery contracts",
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
        "Shared trading authorities require core and forward-recovery verification",
    ),
    VerificationImpactRule(
        "cn-ashare-market",
        ("packages/market/onlyalpha-market-cn-ashare/", "tests/conformance/cn_a_share_cash/"),
        (),
        (OnlyTestLane.ASHARE, OnlyTestLane.CORE_FULL, OnlyTestLane.RECOVERY),
        STATIC,
        VerificationEscalation.BROAD,
        "A-share market semantics feed durable core execution",
    ),
    VerificationImpactRule(
        "generic-market",
        ("packages/market/onlyalpha-market-generic-t0-cash/",),
        (),
        (OnlyTestLane.CORE_FULL, OnlyTestLane.RECOVERY, OnlyTestLane.SIM_RECOVERY),
        STATIC,
        VerificationEscalation.BROAD,
        "Generic market product is shared by durable Backtest and SIM paths",
    ),
    VerificationImpactRule(
        "miniqmt-provider",
        ("packages/provider/onlyalpha-plugin-miniqmt/",),
        (),
        (OnlyTestLane.MINIQMT_CONTRACT, OnlyTestLane.RESEARCH_DATASET),
        STATIC,
        VerificationEscalation.COMPONENT,
        "MiniQMT contract and historical Dataset admission are affected",
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
        "binance-spot",
        ("packages/market/onlyalpha-market-binance-spot/", "packages/provider/onlyalpha-plugin-binance/"),
        (),
        (OnlyTestLane.CORE_FULL,),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Binance Spot Market Product/DataSource composition affects provider-neutral trading consumers",
    ),
    VerificationImpactRule(
        "strategy-product",
        ("src/onlyalpha/strategy/", "tests/strategy/", "src/onlyalpha/cluster/factory.py"),
        ("tests/architecture/test_p9_strategy_authority.py", "src/onlyalpha/config/models.py"),
        (OnlyTestLane.STRATEGY, OnlyTestLane.CALCULATION),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Strategy Revision, Freeze and Trading Admission form one product authority",
    ),
    VerificationImpactRule(
        "package-metadata",
        (),
        ("pyproject.toml", "uv.lock", "packages/api/onlyalpha-api/pyproject.toml"),
        (),
        STATIC,
        VerificationEscalation.COMPONENT,
        "Distribution metadata requires consistency and targeted package build checks",
    ),
    VerificationImpactRule(
        "shared-test-infrastructure",
        ("tests/fixtures/", "tests/support/", "tests/architecture/"),
        (),
        (OnlyTestLane.ARCHITECTURE, OnlyTestLane.FAST, OnlyTestLane.INTEGRATION),
        STATIC,
        VerificationEscalation.BROAD,
        "Shared fixtures/support/architecture checks can affect multiple nearby canonical lanes",
        (
            "tests/architecture/test_research_specification_boundaries.py",
            "tests/architecture/test_research_run_boundaries.py",
            "tests/architecture/test_postgres_operational_authority.py",
            "tests/architecture/test_research_result_boundaries.py",
            "tests/architecture/test_research_query_boundaries.py",
            "tests/architecture/test_quality_policy_contract.py",
            "tests/architecture/test_task_acceptance_policy.py",
        ),
    ),
    VerificationImpactRule(
        "docs-only",
        ("docs/", "prompts/"),
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
        if path in {"pyproject.toml", "uv.lock", "packages/api/onlyalpha-api/pyproject.toml"}
    }
    version_sync_required = "package-metadata" in rules
    build_targets = (
        ("onlyalpha", "onlyalpha-api")
        if "packages/api/onlyalpha-api/pyproject.toml" in metadata_paths
        else ("onlyalpha",)
        if metadata_paths
        else ()
    )
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
                for path in changed.impact_paths()
                if path.endswith(".py") and changed.kind is not ChangeKind.DELETED
            }
        )
    )
    typed_roots = {
        "strategy-product": ("src/onlyalpha/strategy", "src/onlyalpha/calculation"),
        "research-definition": ("src/onlyalpha/research/definition",),
        "research-runtime": ("src/onlyalpha/runtime/research", "src/onlyalpha/runtime/product.py"),
        "research-specification": ("src/onlyalpha/research/specification",),
        "research-run": ("src/onlyalpha/research/run",),
        "research-execution": ("src/onlyalpha/research/execution",),
        "research-postgres": ("src/onlyalpha/persistence/postgres",),
        "research-workload": (
            "src/onlyalpha/research/specification",
            "src/onlyalpha/research/workload.py",
            "src/onlyalpha/runtime/research",
        ),
        "research-artifact": ("src/onlyalpha/research/artifact",),
        "research-query": ("src/onlyalpha/research/query", "packages/api/onlyalpha-api/src/onlyalpha_api"),
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
    return run_plan(plan, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
