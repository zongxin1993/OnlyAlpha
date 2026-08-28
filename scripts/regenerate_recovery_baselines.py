from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
import tempfile
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onlyalpha.config import OnlyClusterRunConfig  # noqa: E402
from onlyalpha.domain.identifiers import OnlyEngineId  # noqa: E402
from onlyalpha.engine import OnlyEngineConfig  # noqa: E402
from onlyalpha.engine.engine import OnlyEngine  # noqa: E402
from onlyalpha.result import only_backtest_business_projection  # noqa: E402
from tests.integration.test_engine_multi_cluster_close_cost_authority import _configs  # noqa: E402
from tests.integration.virtual_multi_fill_support import (  # noqa: E402
    only_terminal_after_partial_fill_config,
    only_virtual_multi_fill_config,
)
from tests.support.canonical import canonical_value, write_canonical_json  # noqa: E402
from tests.support.sqlite_templates import publish_sqlite_template, sqlite_fingerprint  # noqa: E402

TARGET = ROOT / "tests" / "fixtures" / "recovery"
CACHE = ROOT / ".test-cache" / "recovery"
BASELINES = (
    "long_close_whole_baseline",
    "long_close_multi_fill_baseline",
    "multi_cluster_close_baseline",
    "terminal_after_partial_fill_baseline",
)


def _configs_for(name: str, user_data_root: Path) -> tuple[OnlyClusterRunConfig, ...]:
    if name == "long_close_whole_baseline":
        config = only_virtual_multi_fill_config(user_data_root, long_close=True)
        broker = config.brokers[0]
        extensions = json.loads(json.dumps(dict(broker.extensions)))
        del extensions["matching"]["partial_fill"]
        return (replace(config, brokers=(replace(broker, extensions=extensions),)),)
    if name == "long_close_multi_fill_baseline":
        return (only_virtual_multi_fill_config(user_data_root, long_close=True),)
    if name == "multi_cluster_close_baseline":
        configs = _configs(user_data_root)
        persistence = only_virtual_multi_fill_config(user_data_root).runtime.persistence
        return tuple(replace(item, runtime=replace(item.runtime, persistence=persistence)) for item in configs)
    if name == "terminal_after_partial_fill_baseline":
        return (only_terminal_after_partial_fill_config(user_data_root),)
    raise ValueError(name)


def regenerate(name: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"onlyalpha-recovery-{name}-") as raw:
        run_root = Path(raw)
        engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId(f"recovery-{name}"), run_root))
        for config in _configs_for(name, run_root):
            engine.add_cluster(config)  # type: ignore[arg-type]
        result = engine.run()
        if result.status != "COMPLETED" or not result.runtime_results:
            raise RuntimeError(f"Recovery baseline failed for {name}: {result.failures}")
        runtime_result = result.runtime_results[0]
        broker = engine.runtime_sessions[0].runtime.broker_gateway
        broker_checkpoint = broker.capture_checkpoint()
        databases = tuple(run_root.rglob("*.sqlite3"))
        if len(databases) != 1:
            raise RuntimeError(f"Recovery baseline {name} expected one closed SQLite database, got {databases}")
        database = databases[0]
        fingerprint = sqlite_fingerprint(database)
        template_name = f"{name}-{fingerprint}.sqlite3"
        publish_sqlite_template(database, CACHE / template_name)
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT runtime_id, checkpoint_sequence FROM runtime_checkpoints "
                "ORDER BY checkpoint_sequence DESC LIMIT 1"
            ).fetchone()
            committed_rows = connection.execute(
                "SELECT transaction_id, operation_identity FROM runtime_transactions ORDER BY execution_sequence"
            ).fetchall()
        finally:
            connection.close()
        if row is None:
            raise RuntimeError(f"Recovery baseline has no checkpoint: {name}")
        checkpoint_id = f"{row[0]}:{row[1]}"
        directory = TARGET / name
        directory.mkdir(parents=True, exist_ok=True)
        archive_name = "database.sqlite3.gz"
        with (directory / archive_name).open("wb") as archive_stream:
            with gzip.GzipFile(filename="", mode="wb", fileobj=archive_stream, mtime=0) as compressed:
                with database.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        compressed.write(chunk)
        write_canonical_json(
            directory / "canonical_projection.json",
            canonical_value(only_backtest_business_projection(runtime_result)),
        )
        write_canonical_json(
            directory / "manifest.json",
            {
                "baseline_schema_version": 1,
                "baseline_id": name,
                "scenario_fingerprint": result.determinism_fingerprint,
                "configuration_fingerprint": result.determinism_fingerprint,
                "persistence_schema_version": "5",
                "onlyalpha_version": version("onlyalpha"),
                "database_template": template_name,
                "database_archive": archive_name,
                "database_fingerprint": fingerprint,
                "checkpoint_id": checkpoint_id,
                "result_fingerprint": runtime_result.result_fingerprint,
                "committed_transaction_ids": [item[0] for item in committed_rows],
                "committed_fact_ids": [item[1] for item in committed_rows],
                "order_count": len(runtime_result.orders),
                "fill_count": len(runtime_result.facts.executions),
                "terminal_count": sum(
                    item.status.value in {"CANCELLED", "REJECTED", "EXPIRED"} for item in runtime_result.orders
                ),
                "broker_checkpoint": canonical_value(broker_checkpoint),
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="append", choices=BASELINES)
    args = parser.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    for baseline in args.baseline or BASELINES:
        regenerate(baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
