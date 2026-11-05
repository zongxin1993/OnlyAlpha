"""Regenerate technical Web mutation vectors using native owners.

No vector is served by Shipping. Run only in the frozen canonical serial test
namespace: the producer resets its guarded test schema and dedicated CH database.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURE = ROOT / "test-data/web/chart-studies/query.json"
SUPPORT = ROOT / "packages/backend/tests/application/support"


def _inline(value: Any) -> str:
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{key} = {_inline(item)}" for key, item in value.items()) + " }"
    return json.dumps(value)


def _clear(directory: Path) -> None:
    if directory.is_symlink():
        raise ValueError("CHART_VECTOR_ROOT_SYMLINK")
    if directory.exists():
        if not shutil.rmtree.avoids_symlink_attacks:
            raise ValueError("CHART_VECTOR_SAFE_CLEANUP_REQUIRED")
        for path, _, _ in os.walk(directory, followlinks=False):
            Path(path).chmod(0o700)
        shutil.rmtree(directory)


@functools.lru_cache(maxsize=1)
def _produce() -> str:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from scripts.database_guard import assert_test_database
    from scripts.dev_verification import CUT_METADATA, source_inputs
    from scripts.native_http_contract import native_executable
    from scripts.native_web_e2e import clickhouse_namespace
    from scripts.rust_kernel_check import compiler_environment, isolated_backend, module_path, prepare_cargo_home

    operation = os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    inputs = source_inputs(ROOT)
    cut = json.loads((ROOT / CUT_METADATA).read_text())
    if ROOT != Path("/workspace") or cut["operation_id"] != operation or cut["inputs"] != inputs:
        raise ValueError("CHART_VECTOR_FROZEN_CANONICAL_SOURCE_REQUIRED")
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    assert_test_database(dsn)
    if conninfo_to_dict(dsn).get("sslmode") not in (None, "disable"):
        raise ValueError("CHART_VECTOR_CONTAINED_POSTGRES_TRANSPORT_REQUIRED")
    database = "onlyalpha_test_chart_query_" + operation.replace("-", "")
    backend = native_executable()
    # The native ELF bytes deliberately bind the worker and capability identities.
    root = ROOT / "test-results/chart-query-vector"
    _clear(root)
    root.mkdir()
    evidence = ROOT / "test-results/chart-query-vector-evidence" / operation
    evidence.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location(
        "_chart_native_command", SUPPORT.parent / "test_native_market_source_application.py"
    )
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    command = helper._native_command
    environment = compiler_environment(os.environ, ROOT / "test-results/rust-kernel/target")
    environment["RUSTUP_TOOLCHAIN"] = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(environment["CARGO_HOME"]))
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    command(
        [str(backend), "--migrate-postgres-schema", str(ROOT / "database/postgres/migrations")],
        {**os.environ, "ONLYALPHA_POSTGRES_DSN": make_conninfo(dsn, sslmode="disable")},
        evidence / "postgres-migration.log",
        ROOT,
    )
    clickhouse_namespace(backend, database, initialize=True)
    try:
        manifest = isolated_backend(ROOT, root / "closure")
        consumer = manifest.parent / "native-consumer"
        consumer.mkdir()
        (consumer / "lib.rs").write_text(
            (SUPPORT / "native_market_consumer.rs").read_text()
            + "\nmod chart_vector {\n"
            + (SUPPORT / "native_chart_fixture.rs").read_text()
            + "\n}\n"
        )
        dependencies: dict[str, Any] = {}
        for module in ("backend", "plugin_binance"):
            data = tomllib.loads((ROOT / module_path(module) / "Cargo.toml").read_text())
            for name, value in data["dependencies"].items():
                value = dict(value)
                if "path" in value:
                    value["path"] = os.path.relpath(
                        (manifest.parent / module_path(module) / value["path"]).resolve(), consumer
                    )
                if name in dependencies:
                    previous = dependencies[name]
                    assert {k: v for k, v in previous.items() if k != "features"} == {
                        k: v for k, v in value.items() if k != "features"
                    }
                    value["features"] = sorted(set(previous.get("features", [])) | set(value.get("features", [])))
                dependencies[name] = value
            dependencies[data["package"]["name"]] = {
                "path": os.path.relpath(manifest.parent / module_path(module), consumer)
            }
        (consumer / "Cargo.toml").write_text(
            '[package]\nname="onlyalpha-native-chart-vector"\nversion.workspace=true\nedition.workspace=true\nrust-version.workspace=true\npublish=false\nbuild=false\n[lib]\npath="lib.rs"\ndoctest=false\n[lints]\nworkspace=true\n[dependencies]\n'
            + "\n".join(name + " = " + _inline(value) for name, value in sorted(dependencies.items()))
            + "\n"
        )
        manifest.write_text(manifest.read_text().replace("members = [", 'members = ["native-consumer",', 1))
        command(
            ["cargo", "metadata", "--manifest-path", str(manifest), "--offline", "--format-version", "1"],
            environment,
            evidence / "metadata.json",
            consumer,
            json_output=True,
        )

        def registry(path: Path) -> dict[tuple[str, str, str], str]:
            return {
                (p["name"], p["version"], p["source"]): p["checksum"]
                for p in tomllib.loads(path.read_text())["package"]
                if "source" in p
            }

        admitted = registry(ROOT / "Cargo.lock")
        assert all(admitted.get(key) == value for key, value in registry(manifest.with_name("Cargo.lock")).items()), (
            "unreviewed chart vector dependency"
        )
        command(
            [
                "cargo",
                "metadata",
                "--manifest-path",
                str(ROOT / "Cargo.toml"),
                "--frozen",
                "--offline",
                "--format-version",
                "1",
            ],
            environment,
            evidence / "workspace-metadata.json",
            ROOT,
            json_output=True,
        )
        known = {
            node["id"]: set(node["features"])
            for node in json.loads((evidence / "workspace-metadata.json").read_text())["resolve"]["nodes"]
        }
        for node in json.loads((evidence / "metadata.json").read_text())["resolve"]["nodes"]:
            if node["id"].startswith("registry+"):
                assert set(node["features"]) <= known[node["id"]], "unreviewed chart vector feature"
        environment.update(
            ONLYALPHA_NATIVE_CHART_WORKER=str(backend),
            ONLYALPHA_NATIVE_MARKET_WAL=str(root / "wal"),
            ONLYALPHA_NATIVE_CHART_CLICKHOUSE_DATABASE=database,
            ONLYALPHA_NATIVE_CHART_VECTOR=str(evidence / "native-query.json"),
        )
        (root / "wal").mkdir(mode=0o700)
        target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
        command(
            [
                "cargo",
                "test",
                "--manifest-path",
                str(manifest),
                "-p",
                "onlyalpha-native-chart-vector",
                "--frozen",
                "--offline",
                "--target",
                target,
                "-j1",
                "--release",
                "--no-run",
                "--message-format=json",
            ],
            environment,
            evidence / "build.jsonl",
            consumer,
            json_output=True,
        )
        artifacts = [
            item
            for line in (evidence / "build.jsonl").read_text().splitlines()
            if (item := json.loads(line)).get("reason") == "compiler-artifact"
            and item.get("executable")
            and item["target"]["name"] == "onlyalpha_native_chart_vector"
            and item["profile"]["test"]
        ]
        assert len(artifacts) == 1
        profile = artifacts[0]["profile"]
        assert profile["test"] is True and profile["debug_assertions"] is False and profile["opt_level"] == "3", (
            "CHART_VECTOR_ACTUAL_RELEASE_PROFILE_REQUIRED"
        )
        executable = Path(artifacts[0]["executable"])
        executable_bytes = executable.read_bytes()
        assert executable_bytes[:4] == b"\x7fELF", "CHART_VECTOR_NATIVE_ELF_REQUIRED"
        (evidence / "executable.json").write_text(
            json.dumps(
                {
                    "artifact": artifacts[0],
                    "sha256": hashlib.sha256(executable_bytes).hexdigest(),
                    "source_inputs": inputs,
                },
                indent=2,
            )
        )
        command(
            [str(executable), "--exact", "chart_vector::export_vector", "--nocapture", "--test-threads=1"],
            environment,
            evidence / "native-query.log",
            consumer,
        )
        if source_inputs(ROOT) != inputs:
            raise ValueError("CHART_VECTOR_SOURCE_CHANGED")
        return json.dumps(json.loads((evidence / "native-query.json").read_text()), indent=2, sort_keys=True) + "\n"
    finally:
        clickhouse_namespace(backend, database, initialize=False)


def render() -> str:
    return _produce()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("write", "check"))
    parser.add_argument(
        "--output-dir", type=Path, help="write generated technical outputs without mutating frozen source"
    )
    args = parser.parse_args()
    query = _produce()
    if args.mode == "write":
        destination = args.output_dir or FIXTURE.parent
        destination.mkdir(parents=True, exist_ok=True)
        (destination / FIXTURE.name).write_text(query)
    elif FIXTURE.read_text() != query:
        raise SystemExit("Chart Query vector stale; regenerate with the native producer")


if __name__ == "__main__":
    main()
