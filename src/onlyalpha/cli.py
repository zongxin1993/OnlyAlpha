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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = only_parse_args(argv)
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
        result = engine.run()
        if args.console_report:
            for index, console_report in enumerate(result.console_reports):
                if index:
                    print()
                print(console_report)
        payload = {
            "engine_id": str(result.engine_id),
            "run_id": result.run_id,
            "status": result.status,
            "cluster_count": len(result.cluster_results),
            "failures": list(result.failures),
            "manifest_path": None if result.manifest_path is None else str(result.manifest_path),
            "determinism_fingerprint": result.determinism_fingerprint,
        }
        if len(result.backtest_reports) == 1:
            report_payload = dict(result.backtest_reports[0])
            report_payload.pop("status", None)
            report_payload.pop("cluster_count", None)
            payload.update(report_payload)
            if result.report_paths:
                payload["report_path"] = str(result.report_paths[0])
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return result.exit_code
    except (OSError, ValueError) as exc:
        print(f"onlyalpha: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
