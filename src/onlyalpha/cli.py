"""OnlyAlpha unified product command-line entry."""

from __future__ import annotations

import argparse
import glob
import json
import os
from collections.abc import Sequence
from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.runtime.defaults import only_default_engine_services


def only_resolve_user_data_root(value: str | None) -> Path:
    selected = value or os.environ.get("ONLYALPHA_USER_DATA")
    return Path(selected).expanduser().resolve() if selected else (Path.cwd() / "user_data").resolve()


def only_resolve_config_paths(args: argparse.Namespace) -> tuple[Path, ...]:
    explicit = [Path(item).expanduser().resolve() for item in args.config]
    discovered: list[Path] = []
    if args.config_dir is not None:
        directory = Path(args.config_dir).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError(f"config directory not found: {directory}")
        discovered.extend(
            sorted(
                (
                    item.resolve()
                    for item in directory.rglob("*")
                    if item.is_file() and item.name.lower() in {"config.yaml", "config.yml", "config.json"}
                ),
                key=str,
            )
        )
    if args.config_glob is not None:
        discovered.extend(sorted((Path(item).expanduser().resolve() for item in glob.glob(args.config_glob)), key=str))
    result: list[Path] = []
    seen: set[Path] = set()
    for item in (*explicit, *discovered):
        if item not in seen:
            seen.add(item)
            result.append(item)
    if not result:
        raise ValueError("at least one --config, --config-dir or --config-glob is required")
    return tuple(result)


def only_parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="onlyalpha")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--config", action="append", default=[], metavar="PATH")
    run_parser.add_argument("--config-dir", metavar="DIRECTORY")
    run_parser.add_argument("--config-glob", metavar="PATTERN")
    run_parser.add_argument("--user-data", metavar="DIRECTORY")
    run_parser.add_argument("--engine-id", default="onlyalpha")
    run_parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--fail-fast", action=argparse.BooleanOptionalAction, default=True)
    run_parser.add_argument("--console-report", action="store_true")
    scenario_parser = subparsers.add_parser("scenario")
    scenario_commands = scenario_parser.add_subparsers(dest="scenario_command", required=True)
    scenario_validate = scenario_commands.add_parser("validate")
    scenario_validate.add_argument("file")
    scenario_validate.add_argument("--format", choices=("text", "json"), default="text")
    scenario_run = scenario_commands.add_parser("run")
    scenario_run.add_argument("file")
    scenario_run.add_argument("--user-data", metavar="DIRECTORY")
    scenario_run.add_argument("--format", choices=("text", "json"), default="text")
    market_parser = subparsers.add_parser("market")
    market_commands = market_parser.add_subparsers(dest="market_command", required=True)
    market_profiles = market_commands.add_parser("profiles")
    market_profiles.add_argument("--format", choices=("text", "json"), default="text")
    market_profile = market_commands.add_parser("profile")
    market_profile.add_argument("profile_id")
    market_profile.add_argument("--version")
    market_profile.add_argument("--format", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = only_parse_args(argv)
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
        if args.command == "market":
            from dataclasses import asdict

            from onlyalpha.application import OnlyMarketProfileQueryService
            from onlyalpha.market.profiles import only_builtin_market_profile_registry

            query = OnlyMarketProfileQueryService(only_builtin_market_profile_registry())
            value = (
                query.list_profiles()
                if args.market_command == "profiles"
                else query.profile(args.profile_id, args.version)
            )
            normalized = [asdict(item) for item in value] if isinstance(value, tuple) else asdict(value)
            print(json.dumps(normalized, sort_keys=True) if args.format == "json" else json.dumps(normalized, indent=2))
            return 0
        engine = OnlyEngine(
            OnlyEngineConfig(
                OnlyEngineId(args.engine_id),
                only_resolve_user_data_root(args.user_data),
                fail_fast=args.fail_fast,
                log_level=args.log_level,
            ),
            services=only_default_engine_services(fail_fast=args.fail_fast),
        )
        for config_path in only_resolve_config_paths(args):
            try:
                engine.add_cluster_from_file(config_path)
            except (OSError, ValueError) as exc:
                if args.fail_fast:
                    raise
                print(f"onlyalpha: skipped {config_path}: {exc}")
        if args.dry_run:
            validation = engine.validate()
            print(validation.render())
            return validation.exit_code
        engine_result = engine.run()
        if args.console_report:
            for index, console_report in enumerate(engine_result.console_reports):
                if index:
                    print()
                print(console_report)
        payload = {
            "engine_id": str(engine_result.engine_id),
            "run_id": engine_result.run_id,
            "status": engine_result.status,
            "cluster_count": len(engine_result.cluster_results),
            "failures": list(engine_result.failures),
            "manifest_path": None if engine_result.manifest_path is None else str(engine_result.manifest_path),
            "determinism_fingerprint": engine_result.determinism_fingerprint,
        }
        if len(engine_result.backtest_reports) == 1:
            report_payload = dict(engine_result.backtest_reports[0])
            report_payload.pop("status", None)
            report_payload.pop("cluster_count", None)
            payload.update(report_payload)
            if engine_result.report_paths:
                payload["report_path"] = str(engine_result.report_paths[0])
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return engine_result.exit_code
    except (OSError, ValueError) as exc:
        print(f"onlyalpha: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
