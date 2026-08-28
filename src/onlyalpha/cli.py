"""OnlyAlpha unified product command-line entry."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from onlyalpha.core.errors import OnlyError


def only_resolve_user_data_root(value: str | None) -> Path:
    selected = value or os.environ.get("ONLYALPHA_USER_DATA")
    return Path(selected).expanduser().resolve() if selected else (Path.cwd() / "user_data").resolve()


def only_parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="onlyalpha")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scenario_parser = subparsers.add_parser("scenario")
    scenario_commands = scenario_parser.add_subparsers(dest="scenario_command", required=True)
    scenario_validate = scenario_commands.add_parser("validate")
    scenario_validate.add_argument("file")
    scenario_validate.add_argument("--format", choices=("text", "json"), default="text")
    scenario_run = scenario_commands.add_parser("run")
    scenario_run.add_argument("file")
    scenario_run.add_argument("--user-data", metavar="DIRECTORY")
    scenario_run.add_argument("--format", choices=("text", "json"), default="text")
    operations_parser = subparsers.add_parser("operations")
    operations_commands = operations_parser.add_subparsers(dest="operations_command", required=True)
    operations_status = operations_commands.add_parser("status")
    operations_status.add_argument("--limit", type=int, default=100)
    operations_run = operations_commands.add_parser("run")
    operations_run.add_argument("run_id")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = only_parse_args(argv)
        if args.command == "operations":
            from onlyalpha.persistence.postgres import OnlyPostgresConfig, OnlyPostgresResearchOperationsStore
            from onlyalpha.research.operations.diagnostics import OnlyResearchOperationalDiagnosticService
            from onlyalpha.research.run import OnlyResearchRunId

            store = OnlyPostgresResearchOperationsStore(OnlyPostgresConfig.from_environment().dsn)
            run_id = None if args.operations_command == "status" else OnlyResearchRunId(args.run_id)
            snapshot = store.load_operational_snapshot(
                run_id=run_id,
                limit=args.limit if args.operations_command == "status" else 1,
            )
            diagnoses = OnlyResearchOperationalDiagnosticService().diagnose(snapshot)
            payload: dict[str, object] = {
                "observed_at": snapshot.observed_at.isoformat(),
                "workers": [
                    {
                        "worker_instance_id": str(item.worker_instance_id),
                        "started_at": item.started_at.isoformat(),
                        "last_seen_at": item.last_seen_at.isoformat(),
                        "service_version": item.service_version,
                        "draining_since": None if item.draining_since is None else item.draining_since.isoformat(),
                    }
                    for item in snapshot.workers
                ],
                "runs": [
                    {
                        "run_id": str(item.record.run.run_id),
                        "revision": item.record.run.revision,
                        "state": item.record.run.state.value,
                        "specification_fingerprint": item.record.run.specification_fingerprint,
                        "diagnosis": item.code.value,
                        "queued_at": item.record.run.queued_at.isoformat(),
                        "started_at": None
                        if item.record.run.started_at is None
                        else item.record.run.started_at.isoformat(),
                        "cancel_requested_at": None
                        if item.record.run.cancel_requested_at is None
                        else item.record.run.cancel_requested_at.isoformat(),
                        "finished_at": None
                        if item.record.run.finished_at is None
                        else item.record.run.finished_at.isoformat(),
                        "research_result_fingerprint": item.record.run.research_result_fingerprint,
                        "artifact_content_fingerprint": item.record.run.artifact_content_fingerprint,
                        "failure": None
                        if item.record.run.failure is None
                        else {
                            "phase": item.record.run.failure.phase.value,
                            "code": item.record.run.failure.code,
                            "detail": item.record.run.failure.detail,
                        },
                        "attempts": [
                            {
                                "attempt_id": str(attempt.attempt_id),
                                "attempt_number": attempt.attempt_number,
                                "state": attempt.state.value,
                                "worker_instance_id": str(attempt.worker_instance_id),
                                "claimed_at": attempt.claimed_at.isoformat(),
                                "last_heartbeat_at": attempt.last_heartbeat_at.isoformat(),
                                "lease_expires_at": attempt.lease_expires_at.isoformat(),
                                "finished_at": None if attempt.finished_at is None else attempt.finished_at.isoformat(),
                                "failure_code": None if attempt.failure is None else attempt.failure.code,
                            }
                            for attempt in item.record.attempts
                        ],
                    }
                    for item in diagnoses
                ],
            }
            print(json.dumps(payload, sort_keys=True))
            return 0
        if args.command == "scenario":
            from dataclasses import asdict

            from onlyalpha.scenario import (
                OnlyMarketScenarioParser,
                OnlyMarketScenarioRunner,
                OnlyMarketScenarioRunRequest,
            )

            scenario = OnlyMarketScenarioParser().load(args.file)
            if args.scenario_command == "validate":
                payload = {"scenario_id": str(scenario.scenario_id), "version": str(scenario.version), "valid": True}
                print(
                    json.dumps(payload, sort_keys=True)
                    if args.format == "json"
                    else f"VALID {scenario.scenario_id}@{scenario.version}"
                )
                return 0
            scenario_result = OnlyMarketScenarioRunner().run(
                OnlyMarketScenarioRunRequest(scenario, only_resolve_user_data_root(args.user_data))
            )
            payload = {
                "scenario_id": scenario_result.scenario_id,
                "version": scenario_result.scenario_version,
                "status": scenario_result.status,
                "input_fingerprint": scenario_result.input_fingerprint,
                "result_fingerprint": scenario_result.result_fingerprint,
                "artifact_path": None if scenario_result.artifact_path is None else str(scenario_result.artifact_path),
                "assertions": [asdict(item) for item in scenario_result.assertions.results],
            }
            print(
                json.dumps(payload, default=str, sort_keys=True)
                if args.format == "json"
                else f"{scenario_result.status} {scenario_result.scenario_id}@{scenario_result.scenario_version} "
                f"{scenario_result.result_fingerprint}"
            )
            return {"PASSED": 0, "FAILED": 1, "ERROR": 3}.get(scenario_result.status, 3)
        raise RuntimeError(f"unsupported root CLI command: {args.command}")
    except (OSError, ValueError, RuntimeError, OnlyError) as exc:
        print(f"onlyalpha: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
