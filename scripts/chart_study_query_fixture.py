"""Regenerate technical Web mutation vectors using native owners and the pure SDK.

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
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURE = ROOT / "test-data/web/chart-studies/query.json"
NUMERIC_CASES = FIXTURE.with_name("numeric-cases.json")
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
def _produce() -> tuple[str, str]:
    import psycopg

    from onlyalpha.persistence.clickhouse import (
        OnlyClickHouseClient,
        OnlyClickHouseConfig,
        OnlyClickHouseMigrationAuthority,
        only_assert_clickhouse_test_database,
    )
    from onlyalpha.persistence.postgres import only_assert_postgres_test_database
    from scripts.dev_verification import CUT_METADATA, source_inputs
    from scripts.rust_kernel_check import _isolated_modules, compiler_environment, module_path, prepare_cargo_home

    operation = os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    inputs = source_inputs(ROOT)
    cut = json.loads((ROOT / CUT_METADATA).read_text())
    if ROOT != Path("/workspace") or cut["operation_id"] != operation or cut["inputs"] != inputs:
        raise ValueError("CHART_VECTOR_FROZEN_CANONICAL_SOURCE_REQUIRED")
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    database = "onlyalpha_test_chart_query_vector"
    only_assert_clickhouse_test_database(database)
    ch = OnlyClickHouseClient(
        OnlyClickHouseConfig(
            os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
            database=database,
            user=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_USER", "default"),
            password=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD", ""),
            storage_policy=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY", "hot_cold"),
        )
    )
    # The ordinary product database is forbidden by the guard above. This
    # producer shares the canonical serial test lifecycle, never business state.
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    subprocess.run([sys.executable, "-m", "scripts.database", "migrate"], cwd=ROOT, check=True)
    ch.execute(f"DROP DATABASE IF EXISTS {database} SYNC", database="default")
    OnlyClickHouseMigrationAuthority(ch).migrate()
    # A stable original build/install path is necessary: both actual native ELF
    # bytes and exact SDK installation are deliberate fingerprint inputs.
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
    modules = (
        "domain",
        "calculation",
        "market_data_construction",
        "strategy",
        "metadata_json",
        "integration_contract",
        "event",
        "market_data_state",
        "market_data_delivery",
        "market_data_pipeline",
        "gateway_protocol",
        "calculation_bridge",
        "backend",
        "plugin_binance",
        "plugin_tushare",
    )
    try:
        manifest = _isolated_modules(ROOT, root / "closure", modules)
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
            dependencies["onlyalpha-" + module.replace("_", "-")] = {
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
        installation = root / "algorithms"
        installation_log = evidence / "algorithm-installation.log"
        command(
            [
                sys.executable,
                str(ROOT / "scripts/build_algorithm_sdk.py"),
                str(root / "wheels"),
                "--install",
                str(installation),
            ],
            environment,
            installation_log,
            ROOT,
        )
        artifact = installation_log.read_text().strip()
        assert len(artifact) == 64 and all(c in "0123456789abcdef" for c in artifact)
        assert hashlib.sha256((installation / "algorithm-installation.json").read_bytes()).hexdigest() == artifact
        environment.update(
            ONLYALPHA_NATIVE_CHART_INSTALLATION=str(installation),
            ONLYALPHA_NATIVE_CHART_ARTIFACT=artifact,
            ONLYALPHA_NATIVE_MARKET_WAL=str(root / "wal"),
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
                    "algorithm_artifact": artifact,
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
        numeric = json.loads((installation / "algorithm-installation.json").read_text())
        numeric_code = (
            "import sys;sys.path="
            + repr(numeric["python_paths"])
            + ";exec("
            + repr((SUPPORT / "chart_numeric_fixture.py").read_text())
            + ")"
        )
        command(
            [str(installation / "bin/python"), "-B", "-I", "-c", numeric_code],
            environment,
            evidence / "numeric.json",
            ROOT,
        )
        if source_inputs(ROOT) != inputs:
            raise ValueError("CHART_VECTOR_SOURCE_CHANGED")
        rendered = [
            json.dumps(json.loads((evidence / name).read_text()), indent=2, sort_keys=True) + "\n"
            for name in ("native-query.json", "numeric.json")
        ]
        return rendered[0], rendered[1]
    finally:
        ch.execute(f"DROP DATABASE IF EXISTS {database} SYNC", database="default")


def render() -> str:
    return _produce()[0]


def render_numeric_cases() -> str:
    return _produce()[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("write", "check"))
    parser.add_argument(
        "--output-dir", type=Path, help="write generated technical outputs without mutating frozen source"
    )
    args = parser.parse_args()
    query, numeric = _produce()
    if args.mode == "write":
        destination = args.output_dir or FIXTURE.parent
        destination.mkdir(parents=True, exist_ok=True)
        (destination / FIXTURE.name).write_text(query)
        (destination / NUMERIC_CASES.name).write_text(numeric)
    elif FIXTURE.read_text() != query or NUMERIC_CASES.read_text() != numeric:
        raise SystemExit("Chart Query vector stale; regenerate with the native producer")


if __name__ == "__main__":
    main()
