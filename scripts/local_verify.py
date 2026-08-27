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
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify import (  # noqa: E402
    VerificationPlan,
    plan_for_change_set,
    resolve_change_set,
    run_plan,
    verification_commands,
)

DEFAULT_BUDGET_UNITS = 10
CI_REQUIRED_EXIT_CODE = 3
LOG_ROOT = ROOT / "test-results" / "verification" / "local-budget"

HEAVY_GATES = frozenset(
    {
        "check:web-e2e",
        "check:build",
        "lane:research-postgres",
        "lane:research-product-closure",
        "lane:core-full",
        "lane:recovery",
        "lane:sim-recovery",
        "lane:exhaustive",
    }
)


@dataclass(frozen=True, slots=True)
class LocalVerificationCommand:
    gate: str
    command: tuple[str, ...]
    cost_units: int

    def as_json(self) -> dict[str, object]:
        return {
            "gate": self.gate,
            "command": list(self.command),
            "cost_units": self.cost_units,
        }


@dataclass(frozen=True, slots=True)
class LocalVerificationExecutionPlan:
    required: tuple[LocalVerificationCommand, ...]
    local: tuple[LocalVerificationCommand, ...]
    deferred_to_ci: tuple[LocalVerificationCommand, ...]
    budget_units: int
    estimated_units: int
    full_local: bool

    @property
    def ci_required(self) -> bool:
        return bool(self.deferred_to_ci)

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "authority": "LOCAL_EXECUTION_POLICY_ONLY",
            "budget_units": self.budget_units,
            "estimated_units": self.estimated_units,
            "full_local": self.full_local,
            "ci_required": self.ci_required,
            "required_commands": [item.as_json() for item in self.required],
            "local_commands": [item.as_json() for item in self.local],
            "deferred_to_ci": [item.as_json() for item in self.deferred_to_ci],
        }


@dataclass(frozen=True, slots=True)
class LocalVerificationStepResult:
    gate: str
    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float
    log_path: str

    def as_json(self) -> dict[str, object]:
        return {
            "gate": self.gate,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "log_path": self.log_path,
        }


def gate_cost_units(gate: str) -> int:
    """Return deterministic scheduling cost. Cost is not quality authority."""
    if gate in HEAVY_GATES:
        return 10
    if gate.startswith("check:release-static"):
        return 1
    if gate.startswith("check:web-"):
        return 3
    if gate.startswith("lane:"):
        return 2
    return 1


def _is_low_cost_preflight(gate: str) -> bool:
    return (
        gate.startswith("check:release-static")
        or gate.startswith("check:affected-")
        or gate in {"check:import-linter", "check:version-sync"}
        or gate.startswith("check:build-")
    )


def build_execution_plan(
    plan: VerificationPlan,
    *,
    budget_units: int = DEFAULT_BUDGET_UNITS,
    full_local: bool = False,
) -> LocalVerificationExecutionPlan:
    if budget_units < 0:
        raise ValueError("budget_units must be >= 0")

    required = tuple(
        LocalVerificationCommand(gate, command, gate_cost_units(gate))
        for gate, command in verification_commands(plan)
    )
    estimated_units = sum(item.cost_units for item in required)

    if full_local or estimated_units <= budget_units:
        return LocalVerificationExecutionPlan(
            required=required,
            local=required,
            deferred_to_ci=(),
            budget_units=budget_units,
            estimated_units=estimated_units,
            full_local=full_local,
        )

    non_heavy = tuple(item for item in required if item.gate not in HEAVY_GATES)
    non_heavy_units = sum(item.cost_units for item in non_heavy)
    if non_heavy_units <= budget_units:
        local = non_heavy
    else:
        local_items: list[LocalVerificationCommand] = []
        used = 0
        for item in required:
            if not _is_low_cost_preflight(item.gate):
                continue
            if used + item.cost_units > budget_units:
                continue
            local_items.append(item)
            used += item.cost_units
        local = tuple(local_items)

    local_gates = {item.gate for item in local}
    deferred = tuple(item for item in required if item.gate not in local_gates)
    return LocalVerificationExecutionPlan(
        required=required,
        local=local,
        deferred_to_ci=deferred,
        budget_units=budget_units,
        estimated_units=estimated_units,
        full_local=full_local,
    )


def _print_execution_plan(
    verification_plan: VerificationPlan,
    execution_plan: LocalVerificationExecutionPlan,
    output: TextIO = sys.stdout,
) -> None:
    payload = {
        "verification_plan": verification_plan.as_json(),
        "execution_policy": execution_plan.as_json(),
    }
    json.dump(payload, output, indent=2, sort_keys=True)
    output.write("\n")


def _safe_gate_name(gate: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", gate)


def _run_command(
    item: LocalVerificationCommand,
    log_root: Path,
    *,
    verbose: bool,
) -> LocalVerificationStepResult:
    log_path = log_root / f"{_safe_gate_name(item.gate)}.log"
    started = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8") as output:
            output.write(f"cwd: {ROOT}\ncommand: {shlex.join(item.command)}\n\n")
            output.flush()
            process = subprocess.run(
                item.command,
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=False,
                text=True,
            )
    except OSError as exc:
        log_path.write_text(f"runner failure: {exc}\n", encoding="utf-8")
        return LocalVerificationStepResult(
            item.gate,
            item.command,
            127,
            round(time.monotonic() - started, 6),
            str(log_path.relative_to(ROOT)),
        )

    if verbose:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        print(content, end="" if content.endswith("\n") else "\n")

    return LocalVerificationStepResult(
        item.gate,
        item.command,
        process.returncode,
        round(time.monotonic() - started, 6),
        str(log_path.relative_to(ROOT)),
    )


def _print_step(result: LocalVerificationStepResult) -> None:
    status = "PASS" if result.exit_code == 0 else "FAIL"
    print(f"{status} {result.gate:<30} {result.duration_seconds:7.2f}s")
    if result.exit_code:
        log_path = ROOT / result.log_path
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"exit_code={result.exit_code}")
        print(f"command: {shlex.join(result.command)}")
        print("diagnostic:")
        print("\n".join(lines[-60:]))
        print(f"full log: {result.log_path}")


def run_budgeted_plan(
    verification_plan: VerificationPlan,
    execution_plan: LocalVerificationExecutionPlan,
    *,
    verbose: bool = False,
) -> int:
    if execution_plan.full_local:
        print("FULL_LOCAL explicit opt-in")
        return run_plan(verification_plan, verbose=verbose)

    if not execution_plan.ci_required:
        return run_plan(verification_plan, verbose=verbose)

    run_id = (
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{verification_plan.change_set.head_revision[:12]}-{os.getpid()}"
    )
    log_root = LOG_ROOT / run_id
    log_root.mkdir(parents=True, exist_ok=False)

    results: list[LocalVerificationStepResult] = []
    for item in execution_plan.local:
        result = _run_command(item, log_root, verbose=verbose)
        results.append(result)
        _print_step(result)
        if result.exit_code:
            break

    failed = next((result for result in results if result.exit_code), None)
    if failed is not None:
        final_state = "LOCAL_VERIFICATION_FAILED"
        exit_code = 1
    else:
        final_state = (
            "LOCAL_PASS_CI_REQUIRED"
            if execution_plan.local
            else "LOCAL_DEFERRED_TO_CI"
        )
        exit_code = CI_REQUIRED_EXIT_CODE

    manifest = {
        "schema_version": 1,
        "authority": "LOCAL_EXECUTION_POLICY_ONLY",
        "verification_plan": verification_plan.as_json(),
        "execution_policy": execution_plan.as_json(),
        "results": [result.as_json() for result in results],
        "result": final_state,
    }
    (log_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print(final_state)
    print(
        f"local={len(execution_plan.local)} "
        f"deferred_to_ci={len(execution_plan.deferred_to_ci)} "
        f"estimated_units={execution_plan.estimated_units} "
        f"budget_units={execution_plan.budget_units}"
    )
    if execution_plan.deferred_to_ci:
        print("CI REQUIRED:")
        for item in execution_plan.deferred_to_ci:
            print(f"- {item.gate}")
    print(f"manifest: {(log_root / 'manifest.json').relative_to(ROOT)}")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Budgeted local execution over scripts/verify.py impact planning. "
            "Heavy required proof is deferred, never silently skipped."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "run"):
        child = subparsers.add_parser(command)
        child.add_argument("--base", required=True, help="explicit commit used as the change-set base")
        child.add_argument(
            "--budget-units",
            type=int,
            default=DEFAULT_BUDGET_UNITS,
            help="deterministic local scheduling budget; not a quality threshold",
        )
        child.add_argument(
            "--full-local",
            action="store_true",
            help="explicitly execute the entire impact plan locally",
        )
        if command == "run":
            child.add_argument("--verbose", action="store_true")

    args = parser.parse_args()
    try:
        verification_plan = plan_for_change_set(resolve_change_set(args.base))
        execution_plan = build_execution_plan(
            verification_plan,
            budget_units=args.budget_units,
            full_local=args.full_local,
        )
    except ValueError as exc:
        print(f"PLAN_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.command == "plan":
        _print_execution_plan(verification_plan, execution_plan)
        return 0

    return run_budgeted_plan(
        verification_plan,
        execution_plan,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(main())
