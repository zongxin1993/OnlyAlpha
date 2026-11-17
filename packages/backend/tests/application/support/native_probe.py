"""构建并调用实际 Rust Probe；成功工件仅在同一次冻结验证中复用。"""

from __future__ import annotations

import json
import hashlib
import os
import platform
import re
import stat
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[5]


@dataclass(frozen=True)
class _BuildContext:
    root: Path
    target: str
    release: bool
    toolchain: str
    operation_id: str
    source_cut_sha256: str


@dataclass(frozen=True)
class _BuildRecord:
    executable: Path
    sha256: str


# Process-local successful builds only. A directory/marker from an earlier
# process is never a build receipt. The dev runner owns frozen-source admission.
_BUILDS: dict[_BuildContext, _BuildRecord] = {}


def runtime_diagnostic_lines(stderr: str | bytes | None) -> list[str]:
    """保留超时前的阶段，不复制请求、任意错误正文或诊断扩展字段。"""
    if stderr is None:
        return []
    text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    saved = []
    for line in text[-512 * 1024:].splitlines()[-256:]:
        if re.fullmatch(r"\[(?:probe-startup|runtime-environment)\] phase=[a-z_]{1,64} elapsed_(?:us|ms)=[0-9]{1,20}", line):
            saved.append(line)
            continue
        if len(line) > 8192:
            continue
        try:
            row = json.loads(line)
        except (ValueError,RecursionError):
            continue
        if not isinstance(row, dict) or not re.fullmatch(r"runtime-preparation-probe-[0-9]+", str(row.get("process_instance_id", ""))):
            continue
        kind = row.get("event_kind")
        if not isinstance(kind,str) or kind not in {"session_start", "session_end", "operation_start", "operation_end"}:
            continue
        result = {"event_kind": kind, "process_instance_id": row["process_instance_id"]}
        if kind in {"operation_start", "operation_end"}:
            operation = row.get("operation", "")
            if row.get("module") != "backend" or not isinstance(operation, str) or not re.fullmatch(r"runtime\.(?:prepare|resolver)\.[a-z_.]{1,80}", operation):
                continue
            result.update(module="backend", operation=operation)
        if isinstance(row.get("outcome"),str) and row["outcome"] in {"ok", "failed", "incomplete"}:
            result["outcome"] = row["outcome"]
        for key in ("schema_version", "pid", "mono_ns", "start_mono_ns", "end_mono_ns", "duration_ns", "work_items", "bytes", "dropped_events", "io_errors"):
            value = row.get(key)
            if type(value) is int and 0 <= value <= 2**64-1:
                result[key] = value
        # The real observability wire format uses decimal strings for span IDs.
        for key in ("span_id","parent_span_id"):
            value=row.get(key)
            if isinstance(value,str) and re.fullmatch(r"[0-9]{1,20}",value) and int(value)<=2**64-1:
                result[key]=value
        if type(row.get("shutdown_complete")) is bool:
            result["shutdown_complete"] = row["shutdown_complete"]
        saved.append(json.dumps(result, sort_keys=True))
    return saved


def _context(release: bool) -> tuple[_BuildContext, dict[str, str]]:
    from scripts.dev_verification import CUT_METADATA
    from scripts.rust_kernel_check import compiler_environment

    root = ROOT.resolve()
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    toolchain = tomllib.loads((root / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    environment = compiler_environment(os.environ, root / "test-results/rust-kernel/target")
    environment["RUSTUP_TOOLCHAIN"] = toolchain
    operation = os.environ.get("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID", "")
    cut_sha = ""
    if operation:
        marker = root / CUT_METADATA
        try:
            with os.fdopen(os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError("NATIVE_PROBE_SOURCE_CUT_INVALID")
                raw = source.read()
        except OSError as error:
            raise ValueError("NATIVE_PROBE_SOURCE_CUT_UNAVAILABLE") from error
        cut = json.loads(raw)
        if not isinstance(cut, dict) or cut.get("operation_id") != operation or not isinstance(cut.get("inputs"), dict):
            raise ValueError("NATIVE_PROBE_SOURCE_CUT_INVALID")
        inputs = cut["inputs"]
        for name in ("Cargo.lock", "rust-toolchain.toml"):
            if inputs.get(name) != hashlib.sha256((root / name).read_bytes()).hexdigest():
                raise ValueError("NATIVE_PROBE_SOURCE_CUT_MISMATCH")
        cut_sha = hashlib.sha256(raw).hexdigest()
    return _BuildContext(root, target, release, toolchain, operation, cut_sha), environment


def _image_sha(path: Path, release: bool) -> str:
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as image:
            before = os.fstat(image.fileno())
            if (not stat.S_ISREG(before.st_mode) or not before.st_mode & 0o111
                    or before.st_mode & 0o022 or before.st_size <= 0
                    or release and before.st_size > 128 * 1024 * 1024):
                raise ValueError("NATIVE_PROBE_ARTIFACT_INVALID")
            digest = hashlib.file_digest(image, "sha256").hexdigest()
            after = os.fstat(image.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("NATIVE_PROBE_ARTIFACT_CHANGED_DURING_READ")
            return digest
    except OSError as error:
        raise ValueError("NATIVE_PROBE_ARTIFACT_UNAVAILABLE") from error


def build_native_probe(release: bool = False) -> Path:
    """Build from the admitted image, reusing only this frozen operation's result."""
    from scripts.rust_kernel_check import prepare_cargo_home

    context, environment = _context(release)
    record = _BUILDS.get(context) if context.operation_id else None
    if record is not None:
        try:
            if _image_sha(record.executable, release) != record.sha256 or _context(release)[0] != context:
                raise ValueError("NATIVE_PROBE_ARTIFACT_MISMATCH")
        except (OSError, ValueError, KeyError):
            _BUILDS.pop(context, None)
            raise
        return record.executable

    root, target = context.root, context.target
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(environment["CARGO_HOME"]))
    command = ["cargo", "build", "--frozen", "--offline", "--target", target, "-j1",
               "-p", "onlyalpha-backend", "--example", "command-postgres-probe"]
    if release:
        command.append("--release")
    subprocess.run(command, cwd=root, env=environment, check=True)
    executable = Path(environment["CARGO_TARGET_DIR"]) / target / (
        "release" if release else "debug") / "examples/command-postgres-probe"
    record = _BuildRecord(executable, _image_sha(executable, release))
    if _context(release)[0] != context:
        raise ValueError("NATIVE_PROBE_SOURCE_CUT_CHANGED_DURING_BUILD")
    if context.operation_id:
        _BUILDS[context] = record
    return executable


def call(probe: Path, request: dict[str, Any], *, dsn: str | None = None) -> dict[str, Any]:
    environment = None if dsn is None else {**os.environ, "ONLYALPHA_POSTGRES_DSN": dsn}
    result = subprocess.run(
        [str(probe)], input=json.dumps(request), text=True, capture_output=True, timeout=20, env=environment
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert isinstance(value, dict), "native PostgreSQL probe must return one JSON object"
    return cast(dict[str, Any], value)
