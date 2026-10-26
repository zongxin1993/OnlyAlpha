"""Exact native Source+Product consumer, isolated canonical PG/CH technical evidence."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from onlyalpha.persistence.clickhouse import (
    OnlyClickHouseClient,
    OnlyClickHouseConfig,
    OnlyClickHouseMigrationAuthority,
    only_assert_clickhouse_test_database,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

ROOT = Path(__file__).resolve().parents[4]
pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(240)]


def _inline(v: object) -> str:
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_inline(x)}" for k, x in v.items()) + " }"
    return json.dumps(v)


@dataclass(frozen=True)
class _NativePrograms:
    environment: dict[str, str]
    evidence: Path
    temporary: Path
    consumer: Path
    executables: dict[str, tuple[Path, str]]


def _preserve_native_failure(temporary: Path) -> None:
    failure = Path(tempfile.mkdtemp(prefix="source-failed-", dir=ROOT / "test-results/rust-product-backend"))
    for item in temporary.iterdir():
        if item.name != "closure":
            if item.is_dir():
                shutil.copytree(item, failure / item.name)
            else:
                shutil.copyfile(item, failure / item.name)
    print("SOURCE_FAILURE_ORIGINALS", failure, flush=True)


def _native_command(
    command: list[str], environment: dict[str, str], log: Path, cwd: Path, *, json_output: bool = False
) -> None:
    # The existing dev launcher also owns a process group. Here each setup or
    # behavior child must be drained even when pytest interrupts its parent wait.
    receipt: dict[str, Any] = {"command": command, "cwd": str(cwd), "timeout_seconds": 240}
    error_log = log.with_suffix(log.suffix + ".stderr.log")
    with log.open("w") as output, error_log.open("w") as errors:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=output,
            stderr=errors if json_output else subprocess.STDOUT,
            start_new_session=True,
        )
        receipt["pid"] = process.pid
        try:
            status = process.wait(timeout=240)
            if status:
                print(log.read_text(), flush=True)
                raise subprocess.CalledProcessError(status, command)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            receipt["exit"] = process.wait(timeout=240)
            remaining = []
            inspection_errors = []
            try:
                for entry in Path("/proc").iterdir():
                    if not entry.name.isdigit():
                        continue
                    try:
                        fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                        if int(fields[2]) == process.pid:
                            remaining.append({"pid": int(entry.name), "state": fields[0]})
                    except (FileNotFoundError, ProcessLookupError):
                        continue
                    except (OSError, ValueError, IndexError) as error:
                        inspection_errors.append(f"{entry.name}: {type(error).__name__}: {error}")
            except OSError as error:
                inspection_errors.append(f"/proc: {type(error).__name__}: {error}")
            receipt["remaining_process_group"] = remaining
            receipt["cleanup_inspection_errors"] = inspection_errors
            receipt["stdout_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
            receipt["stderr_sha256"] = hashlib.sha256(error_log.read_bytes()).hexdigest()
            log.with_suffix(log.suffix + ".process.json").write_text(json.dumps(receipt, indent=2))
            assert not inspection_errors, f"native cleanup inspection failed: {inspection_errors}"
            assert not remaining, f"native child group remains owned: {remaining}"


@pytest.fixture
def native_source_programs(postgres_dsn: str) -> Iterator[_NativePrograms]:
    from scripts.rust_kernel_check import compiler_environment, isolated_backend, module_path, prepare_cargo_home

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    # Existing retained authoring asset is a precondition of this read-only slice.
    from onlyalpha.algorithm.private_factor import ONLY_PRIVATE_FACTOR_API_V1
    from onlyalpha.persistence.postgres.private_asset_store import OnlyPostgresPrivateAssetStore
    from onlyalpha.quant_assets.private import OnlyPrivateFactorAsset, OnlyPrivateFactorDraft

    assets = OnlyPostgresPrivateAssetStore(postgres_dsn)
    factor_id = "private.factor.chart_" + uuid.uuid4().hex
    assets.put_factor_asset(OnlyPrivateFactorAsset(factor_id))
    assets.save_factor_draft(
        OnlyPrivateFactorDraft(
            factor_id=factor_id,
            semantic_version="1",
            source_text="def calculate(api, inputs, parameters):\n    return {'value': inputs['close']}\n",
            factor_api_version=1,
            factor_api_contract_fingerprint=ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
            input_contract={"close": {"type": "DECIMAL"}},
            parameter_contract={},
            output_contract={"value": {"type": "DECIMAL"}},
            description="Retained native metadata",
            economic_rationale="Explicit saved hypothesis",
            category="test",
            tags=("native",),
        )
    )
    _, factor_revision = assets.publish_factor_revision(factor_id)
    assets.save_factor_draft(
        OnlyPrivateFactorDraft(
            factor_id=factor_id,
            semantic_version="2",
            base_revision_fingerprint=factor_revision.revision_fingerprint,
            source_text="def calculate(api, inputs, parameters):\n    return {'value': inputs['close']}\n",
            factor_api_version=1,
            factor_api_contract_fingerprint=ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
            input_contract={"close": {"type": "DECIMAL"}},
            parameter_contract={},
            output_contract={"value": {"type": "DECIMAL"}},
            description="Current head advanced after retained revision",
            economic_rationale="Explicit saved hypothesis",
            category="test",
            tags=("native",),
        )
    )
    _, factor_head = assets.publish_factor_revision(factor_id)
    operation = os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    evidence = ROOT / "test-results/rust-product-backend" / ("chart-consumer-" + operation)
    evidence.mkdir(parents=True)
    (evidence / "factor-precondition.json").write_text(json.dumps(factor_revision.to_dict()))
    database = "onlyalpha_test_native_market_source"
    only_assert_clickhouse_test_database(database)
    config = OnlyClickHouseConfig(
        os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
        database=database,
        user=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_USER", "default"),
        password=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD", ""),
        storage_policy=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY", "hot_cold"),
    )
    ch = OnlyClickHouseClient(config)
    ch.execute(f"DROP DATABASE IF EXISTS {database} SYNC", database="default")
    OnlyClickHouseMigrationAuthority(ch).migrate()
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    output = ROOT / "test-results/rust-kernel/target"
    environment = compiler_environment(os.environ, output)
    environment["ONLYALPHA_NATIVE_FACTOR_METADATA"] = json.dumps(factor_revision.to_dict())
    environment["ONLYALPHA_NATIVE_FACTOR_HEAD"] = json.dumps(factor_head.to_dict())
    environment["RUSTUP_TOOLCHAIN"] = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(environment["CARGO_HOME"]))
    try:
        with (
            tempfile.TemporaryDirectory(prefix="native-market-consumer-", dir=ROOT / "test-results") as temporary,
            tempfile.TemporaryDirectory(prefix="onlyalpha-native-market-wal-", dir="/tmp") as wal_temporary,
        ):
            root = Path(temporary) / "closure"
            manifest = isolated_backend(ROOT, root)
            consumer = root / "native-consumer"
            consumer.mkdir()
            shutil.copyfile(Path(__file__).parent / "support/native_market_consumer.rs", consumer / "lib.rs")
            deps: dict[str, object] = {}
            for module in ("backend", "plugin_binance"):
                data = tomllib.loads((ROOT / module_path(module) / "Cargo.toml").read_text())
                for key, value in data["dependencies"].items():
                    value = dict(value)
                    if "path" in value:
                        value["path"] = os.path.relpath(
                            (root / module_path(module) / value["path"]).resolve(), consumer
                        )
                    if key in deps:
                        prior = deps[key]
                        assert isinstance(prior, dict)
                        assert {k: v for k, v in prior.items() if k != "features"} == {
                            k: v for k, v in value.items() if k != "features"
                        }
                        value["features"] = sorted(set(prior.get("features", [])) | set(value.get("features", [])))
                    deps[key] = value
                deps["onlyalpha-" + module.replace("_", "-")] = {
                    "path": os.path.relpath(root / module_path(module), consumer)
                }
            (consumer / "Cargo.toml").write_text(
                '[package]\nname="onlyalpha-native-market-consumer"\nversion.workspace=true\nedition.workspace=true\nrust-version.workspace=true\npublish=false\nbuild=false\n[lib]\npath="lib.rs"\ndoctest=false\n[lints]\nworkspace=true\n[dependencies]\n'
                + "\n".join(k + " = " + _inline(v) for k, v in sorted(deps.items()))
                + "\n"
            )
            text = manifest.read_text()
            text = text.replace("members = [", 'members = ["native-consumer",', 1)
            manifest.write_text(text)
            # The consumer may shrink the selected graph, never add a registry byte.
            _native_command(
                ["cargo", "metadata", "--manifest-path", str(manifest), "--offline", "--format-version", "1"],
                environment,
                evidence / "consumer-initial-metadata.json",
                root,
                json_output=True,
            )

            def registry(path: Path) -> dict[tuple[str, str, str], str]:
                return {
                    (p["name"], p["version"], p["source"]): p["checksum"]
                    for p in tomllib.loads(path.read_text())["package"]
                    if "source" in p
                }

            selected = registry(ROOT / "Cargo.lock")
            actual = registry(root / "Cargo.lock")
            assert all(selected.get(k) == v for k, v in actual.items()), "unreviewed consumer registry input"

            # Assert actual resolved features are a subset of the selected workspace.
            def metadata(path: Path) -> dict[str, Any]:
                log = evidence / ("root-metadata.json" if path == ROOT / "Cargo.toml" else "consumer-metadata.json")
                _native_command(
                    [
                        "cargo",
                        "metadata",
                        "--manifest-path",
                        str(path),
                        "--frozen",
                        "--offline",
                        "--format-version",
                        "1",
                    ],
                    environment,
                    log,
                    root,
                    json_output=True,
                )
                result: dict[str, Any] = json.loads(log.read_text())
                return result

            admitted = metadata(ROOT / "Cargo.toml")
            effective = metadata(manifest)
            known = {n["id"]: set(n["features"]) for n in admitted["resolve"]["nodes"]}
            for n in effective["resolve"]["nodes"]:
                if n["id"].startswith("registry+"):
                    assert set(n["features"]) <= known[n["id"]], "unreviewed consumer features"
            (evidence / "source-consumer-closure.json").write_text(
                json.dumps({"registry_packages": len(actual), "metadata": effective}, indent=2)
            )
            installation = Path(temporary) / "algorithms"
            install_log = evidence / "algorithm-installation-cli.log"
            _native_command(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_algorithm_sdk.py"),
                    str(Path(temporary) / "algorithm-wheels"),
                    "--install",
                    str(installation),
                ],
                environment,
                install_log,
                ROOT,
            )
            artifact = install_log.read_text().strip()
            assert len(artifact) == 64 and all(c in "0123456789abcdef" for c in artifact)
            assert hashlib.sha256((installation / "algorithm-installation.json").read_bytes()).hexdigest() == artifact
            shutil.copyfile(installation / "algorithm-installation.json", evidence / "algorithm-installation.json")
            shutil.copytree(Path(temporary) / "algorithm-wheels", evidence / "algorithm-wheels")
            (evidence / "algorithm-artifact.json").write_text(
                json.dumps({"artifact_fingerprint": artifact, "root": str(installation)})
            )
            environment["ONLYALPHA_NATIVE_CHART_INSTALLATION"] = str(installation)
            environment["ONLYALPHA_NATIVE_CHART_ARTIFACT"] = artifact
            (Path(wal_temporary) / "wal").mkdir(mode=0o700)
            environment["ONLYALPHA_NATIVE_MARKET_WAL"] = str(Path(wal_temporary) / "wal")
            frames = evidence / "source-emitted-payloads.jsonl"
            frames.write_text("")
            environment["ONLYALPHA_NATIVE_MARKET_OUTPUT"] = str(frames)
            executables: dict[str, tuple[Path, str]] = {}
            try:
                for profile_name, flags in (("debug", []), ("release", ["--release"])):
                    build_log = evidence / f"source-consumer-build-{profile_name}.jsonl"
                    command = [
                        "cargo",
                        "test",
                        "--manifest-path",
                        str(manifest),
                        "-p",
                        "onlyalpha-native-market-consumer",
                        "--frozen",
                        "--offline",
                        "--target",
                        target,
                        "-j1",
                        *flags,
                        "--no-run",
                        "--message-format=json",
                    ]
                    _native_command(command, environment, build_log, consumer, json_output=True)
                    artifacts = [
                        item
                        for line in build_log.read_text().splitlines()
                        if (item := json.loads(line)).get("reason") == "compiler-artifact"
                        and item.get("executable")
                        and item["target"]["name"] == "onlyalpha_native_market_consumer"
                        and item["target"]["src_path"] == str(consumer / "lib.rs")
                        and item["profile"]["test"]
                    ]
                    assert len(artifacts) == 1, "one actual current consumer/test ELF is required"
                    assert artifacts[0]["profile"]["debug_assertions"] is (profile_name == "debug")
                    executable = Path(artifacts[0]["executable"]).resolve(strict=True)
                    executables[profile_name] = (executable, hashlib.sha256(executable.read_bytes()).hexdigest())
                    (evidence / f"source-consumer-elf-{profile_name}.json").write_text(
                        json.dumps(
                            {
                                "artifact": artifacts[0],
                                "sha256": executables[profile_name][1],
                                "command": command,
                                "cwd": str(consumer),
                            },
                            indent=2,
                        )
                    )
                yield _NativePrograms(environment, evidence, Path(temporary), consumer, executables)
            except BaseException:
                _preserve_native_failure(Path(temporary))
                raise
    finally:
        ch.execute(f"DROP DATABASE IF EXISTS {database} SYNC", database="default")


def _validate_native_payloads(frames: Path) -> None:
    # The Product probe result retains its independent canonical restore proof.
    # Every other ORIGINAL emitted frame is consumed by Shipping Web's actual
    # Zod schemas, rather than keeping a retired Python HTTP DTO authority.
    from onlyalpha.canonical import only_canonical_fingerprint
    from onlyalpha.plugin.integration_probe import OnlyIntegrationProbeResult

    for line in frames.read_text().splitlines():
        emitted = json.loads(line)
        if emitted["kind"] == "probe_result":
            OnlyIntegrationProbeResult.restore(emitted["value"], only_canonical_fingerprint(emitted["value"]))

    web = ROOT / "packages/frontend"
    bundle = frames.parent / "native-payload-validator.mjs"
    build = """
import { build } from './node_modules/vite/dist/node/index.js';
await build({
    configFile: false,
    root: process.cwd(),
    logLevel: 'warn',
    ssr: { noExternal: true },
    build: {
        ssr: 'scripts/validate-native-payloads.ts',
        outDir: process.argv[1],
        emptyOutDir: false,
        minify: false,
        sourcemap: false,
        rollupOptions: { output: { entryFileNames: 'native-payload-validator.mjs' } }
    }
});
"""
    environment = dict(os.environ)
    _native_command(
        ["node", "--input-type=module", "-e", build, str(frames.parent)],
        environment,
        frames.parent / "native-payload-validator-build.log",
        web,
    )
    _native_command(
        ["node", str(bundle), str(frames)],
        environment,
        frames.parent / "native-payload-validator.log",
        web,
    )


@pytest.mark.timeout(240, func_only=True)
def test_native_source_and_application(native_source_programs: _NativePrograms) -> None:
    prepared = native_source_programs
    try:
        for profile_name, second in (("debug", False), ("release", True)):
            environment = dict(prepared.environment)
            if second:
                environment["ONLYALPHA_NATIVE_REBUILD_SECOND"] = "1"
            executable, expected_sha = prepared.executables[profile_name]
            assert hashlib.sha256(executable.read_bytes()).hexdigest() == expected_sha
            log = prepared.evidence / f"source-consumer-{profile_name}.log"
            started = time.monotonic()
            _native_command(
                [str(executable), "native_source_application_real_pg_ch", "--exact", "--nocapture", "--test-threads=1"],
                environment,
                log,
                prepared.consumer,
            )
            print("NATIVE_PROFILE", profile_name, "elapsed_seconds", time.monotonic() - started, "exit", 0, flush=True)
        _validate_native_payloads(prepared.evidence / "source-emitted-payloads.jsonl")
    except BaseException:
        _preserve_native_failure(prepared.temporary)
        raise


@pytest.mark.parametrize("failure", ("unreadable", "malformed", "disappeared"))
def test_native_process_inspection_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    original = Path.iterdir
    entry = tmp_path / "712345"
    entry.mkdir()
    if failure == "malformed":
        (entry / "stat").write_text("not a process stat")

    def entries(path: Path) -> Iterator[Path]:
        if path == Path("/proc"):
            if failure == "unreadable":
                raise PermissionError("controlled unavailable proc inspection")
            return iter([entry])
        return original(path)

    monkeypatch.setattr(Path, "iterdir", entries)
    log = tmp_path / "child.log"
    if failure == "disappeared":
        _native_command([sys.executable, "-c", "pass"], dict(os.environ), log, tmp_path)
    else:
        with pytest.raises(AssertionError, match="native cleanup inspection failed"):
            _native_command([sys.executable, "-c", "pass"], dict(os.environ), log, tmp_path)
    receipt = json.loads(log.with_suffix(".log.process.json").read_text())
    assert receipt["exit"] == 0
    assert receipt["remaining_process_group"] == []
    assert bool(receipt["cleanup_inspection_errors"]) is (failure != "disappeared")
