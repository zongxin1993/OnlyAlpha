"""Reusable source-mounted verification in the sole local dev Compose project."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WEB = Path("packages/frontend")
IMAGE = "onlyalpha-browser-test:dev"
ENVIRONMENT_RECORD = Path("/opt/onlyalpha-dev-environment.json")
CONTAINER_LOCK = Path("/tmp/onlyalpha-dev-verification.lock")
HOST_STATE = Path.home() / ".cache/onlyalpha"
CUT_METADATA = ".onlyalpha-dev-source-cut.json"
BROWSER_RESET_FENCE = Path("test-results/dev-verification/browser-reset.pending.json")
# Immutable historical regression inputs, not mutable release baselines. These
# two original commits prove the non-reusable ADR 0109 authorization guard.
HISTORICAL_CONTRACT_TEST_REVISIONS = (
    "8901fec27faf8599c965df792d07a84b902583f3",
    "a09da64745e92848b0f618f7ba5f2bf6ca6771b8",
)
EXCLUDED_DIRECTORIES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".test-cache",
    "test-results",
    "dist",
    "build",
    "htmlcov",
    "coverage",
    ".hypothesis",
    ".import_linter_cache",
}


def environment_inputs(root: Path) -> dict[str, str]:
    paths = [root / name for name in ("pyproject.toml", "uv.lock", "deploy/Dockerfile.dev")]
    paths += [root / WEB / name for name in ("package.json", "package-lock.json")]
    paths += [root / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml") if (root / name).is_file()]
    paths += sorted((root / "crates").rglob("Cargo.toml"))
    paths += sorted((root / "packages").glob("*/Cargo.toml"))
    paths += sorted((root / "plugs").glob("*/Cargo.toml"))
    for directory in ("packages", "plugs"):
        paths += sorted((root / directory).glob("*/pyproject.toml"))
    paths += [
        root / name / "pyproject.toml"
        for name in (
            "test-data/external_plugins/onlyalpha_test_plugin",
            "test-data/runtime_factor_provider",
        )
    ]
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def source_inputs(root: Path) -> dict[str, str]:
    result = {}
    for directory, children, files in os.walk(root):
        children[:] = sorted(name for name in children if name not in EXCLUDED_DIRECTORIES)
        # Root runtime data and host environments are not source. Keep nested
        # env/venv source directories visible and subject to symlink validation.
        if Path(directory) == root:
            children[:] = [name for name in children if name not in {"user_data", "env", "venv", "target"}]
        if any((Path(directory) / name).is_symlink() for name in children):
            raise ValueError("DEV_VERIFICATION_SOURCE_SYMLINK")
        for name in sorted(files):
            if name in {CUT_METADATA, ".DS_Store", ".git"} or name.endswith((".pyc", ".tsbuildinfo")):
                continue
            if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
                continue
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("DEV_VERIFICATION_SOURCE_SYMLINK")
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def git_input_hashes(cut: Path) -> dict[str, str]:
    return {
        str(path.relative_to(cut / ".git")): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((cut / ".git").rglob("*"))
        if path.is_file()
    }


def capture_git(root: Path, cut: Path, previous: dict[str, Any]) -> dict[str, str]:
    """Transport HEAD/tree/index and exact local release base, without remote configuration."""
    if git_input_hashes(cut) != previous.get("git_inputs", {}):
        raise ValueError("DEV_VERIFICATION_GIT_CUT_MODIFIED")
    if not (root / ".git").exists():
        return {}
    git = ["git", "-C", str(root)]
    revision = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True, timeout=15).strip()
    base_result = subprocess.run(
        [*git, "rev-parse", "--verify", "refs/remotes/origin/master"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    base = base_result.stdout.strip() if base_result.returncode == 0 else ""
    historical = (
        HISTORICAL_CONTRACT_TEST_REVISIONS
        if (root / "contracts/product-api/v2/authorized-a0-corrections.json").is_file()
        else ()
    )
    # Missing exact objects are a hard refusal, never a latest/current fallback.
    for required in historical:
        subprocess.run([*git, "cat-file", "-e", required + "^{commit}"], capture_output=True, check=True, timeout=15)
    revisions = list(dict.fromkeys([revision, *([base] if base else []), *historical]))
    index_path = Path(
        subprocess.check_output(
            [*git, "rev-parse", "--path-format=absolute", "--git-path", "index"], text=True, timeout=15
        ).strip()
    )
    index = index_path.read_bytes()
    objects = subprocess.check_output(
        [*git, "rev-list", "--objects", "--no-object-names", "--no-walk", *revisions], timeout=15
    )
    stages = subprocess.check_output([*git, "ls-files", "--stage", "-z"], timeout=15)
    staged_objects = [entry.split(b" ", 2)[1] for entry in stages.split(b"\0") if entry]
    object_ids = sorted(set(objects.splitlines()) | {value for value in staged_objects if value.strip(b"0")})
    pack = subprocess.run(
        [*git, "pack-objects", "--stdout", "--threads=1"],
        input=b"\n".join(object_ids) + b"\n",
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout
    directory = cut / ".git"
    (directory / "objects/pack").mkdir(parents=True, exist_ok=True)
    (directory / "refs").mkdir(exist_ok=True)
    pack_name = "objects/pack/pack-" + hashlib.sha256(pack).hexdigest()
    content = {
        "HEAD": (revision + "\n").encode(),
        "shallow": ("\n".join(revisions) + "\n").encode(),
        "index": index,
        "config": b"[core]\n\trepositoryformatversion = 0\n\tbare = false\n",
        pack_name + ".pack": pack,
    }
    if base:
        content["refs/remotes/origin/master"] = (base + "\n").encode()
    for name, raw in content.items():
        temporary = directory / (name + ".capture")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(raw)
        temporary.replace(directory / name)
    subprocess.run(
        ["git", "index-pack", "-o", str(directory / (pack_name + ".idx")), str(directory / (pack_name + ".pack"))],
        capture_output=True,
        check=True,
        timeout=60,
    )
    retained = {*content, pack_name + ".idx"}
    for name in previous.get("git_inputs", {}):
        if name not in retained:
            (directory / name).unlink()
    if (
        index_path.read_bytes() != index
        or subprocess.check_output([*git, "rev-parse", "HEAD"], text=True, timeout=15).strip() != revision
        or subprocess.run(
            [*git, "rev-parse", "--verify", "refs/remotes/origin/master"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        ).stdout.strip()
        != base
    ):
        raise ValueError("DEV_VERIFICATION_GIT_CHANGED_DURING_CAPTURE")
    return git_input_hashes(cut)


def freeze_source(root: Path, operation_id: str, *, product: bool = False, research: bool = False) -> dict[str, str]:
    """Refresh one managed source view while the host lifecycle reservation is held."""
    from scripts.embed_build_provenance import resolve_build_provenance_bytes, write_build_provenance

    inputs = source_inputs(root)
    cut = root / (".test-cache/dev-product-source" if product else ".test-cache/dev-source-cut")
    marker = cut / CUT_METADATA
    previous: dict[str, Any] = {}
    if product and (cut / ".git").exists():
        raise ValueError("DEV_VERIFICATION_PRODUCT_GIT_REFUSED")
    if cut.is_symlink() or (cut.exists() and not marker.exists()):
        raise ValueError("DEV_VERIFICATION_UNKNOWN_SOURCE_CUT")
    if marker.exists():
        previous = json.loads(marker.read_text())
        if previous.get("source_root") != str(root) or source_inputs(cut) != previous.get("inputs"):
            raise ValueError("DEV_VERIFICATION_SOURCE_CUT_MODIFIED")
        for name in previous["inputs"]:
            if name not in inputs:
                (cut / name).unlink()
                directory = (cut / name).parent
                while (
                    directory != cut
                    and not (root / directory.relative_to(cut)).exists()
                    and not any(directory.iterdir())
                ):
                    directory.rmdir()
                    directory = directory.parent
    cut.mkdir(parents=True, exist_ok=True)
    for name, digest in inputs.items():
        source, target = root / name, cut / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".dev-copy")
        shutil.copyfile(source, temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            temporary.unlink()
            raise ValueError("DEV_VERIFICATION_SOURCE_CHANGED_DURING_CAPTURE")
        temporary.chmod(source.stat().st_mode & 0o555)
        temporary.replace(target)
    # These are mountpoints, not mutable source. Their writable mounts are checked
    # separately; build artifacts and dependency caches never enter the source cut.
    for name in (
        ".venv",
        ".ruff_cache",
        ".mypy_cache",
        ".pytest_cache",
        ".hypothesis",
        ".test-cache",
        "test-results",
        "build",
        str(WEB / "node_modules"),
        str(WEB / "dist"),
    ):
        (cut / name).mkdir(parents=True, exist_ok=True)
    output = root / ".test-cache/dev-tool-output"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("tsconfig.app.tsbuildinfo", "tsconfig.node.tsbuildinfo"):
        for directory in (cut / WEB, output):
            mountpoint = directory / name
            if not mountpoint.exists():
                mountpoint.touch(exist_ok=False)
    if source_inputs(cut) != inputs or source_inputs(root) != inputs:
        raise ValueError("DEV_VERIFICATION_SOURCE_CHANGED_DURING_CAPTURE")
    git_inputs = {} if product else capture_git(root, cut, previous)
    if research:
        provenance = resolve_build_provenance_bytes(cut)
        destination = cut / "src/onlyalpha/_build_provenance.json"
        if not destination.exists():
            write_build_provenance(cut, destination, provenance)
            destination.chmod(0o444)
            destination.with_suffix(".sha256").chmod(0o444)
    frozen_inputs = source_inputs(cut)
    marker.write_text(
        json.dumps(
            {"source_root": str(root), "operation_id": operation_id, "inputs": frozen_inputs, "git_inputs": git_inputs},
            sort_keys=True,
        )
    )
    return inputs


@contextmanager
def host_operation(root: Path, mode: str) -> Iterator[dict[str, Any]]:
    """An interrupted lifecycle is UNKNOWN until explicit owner recovery, not absence."""
    HOST_STATE.mkdir(parents=True, exist_ok=True)
    with (HOST_STATE / "dev-verification.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("DEV_VERIFICATION_BUSY") from error
        pending = HOST_STATE / "dev-verification.pending.json"
        if pending.exists():
            raise ValueError("DEV_VERIFICATION_OUTSTANDING_LIFECYCLE_REQUIRES_OWNER_RECOVERY")
        reservation = {
            "operation_id": str(uuid.uuid4()),
            "source_root": str(root),
            "mode": mode,
            "owner_pid": os.getpid(),
            "completed": False,
        }
        with pending.open("x") as stream:
            json.dump(reservation, stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            yield reservation
        finally:
            if reservation["completed"]:
                pending.unlink()


def validate_container(record: dict[str, Any], root: Path) -> None:
    """Admit observed mounts, not just the Compose declaration or service name."""
    image_id = record.get("Image")
    if (
        not isinstance(image_id, str)
        or len(image_id) != 71
        or not image_id.startswith("sha256:")
        or any(value not in "0123456789abcdef" for value in image_id[7:])
    ):
        raise ValueError("DEV_VERIFICATION_IMAGE_IDENTITY_REQUIRED")
    expected = {
        "/workspace": ("bind", str(root / ".test-cache/dev-source-cut"), False),
        "/onlyalpha-current-source": ("bind", str(root), False),
        "/workspace/test-results": ("bind", str(root / "test-results"), True),
        "/workspace/.venv": ("image", image_id, False),
        "/usr/local/rustup": ("image", image_id, False),
        "/usr/local/cargo": ("image", image_id, False),
        "/workspace/packages/frontend/node_modules": ("image", image_id, False),
        **{
            f"/workspace/{WEB}/{name}": ("bind", str(root / ".test-cache/dev-tool-output" / name), True)
            for name in ("tsconfig.app.tsbuildinfo", "tsconfig.node.tsbuildinfo")
        },
    }
    mounts = record.get("Mounts", [])
    actual = {
        mount.get("Destination"): (
            mount.get("Type"),
            mount.get("Name") if mount.get("Type") == "image" else mount.get("Source"),
            mount.get("RW"),
        )
        for mount in mounts
    }
    # Desktop can independently expose each exact macOS bind through its VM
    # alias. Normalize only that OS alias; expected roots/permissions stay exact.
    desktop_actual = {
        target: (
            kind,
            source.removeprefix("/host_mnt") if kind == "bind" and isinstance(source, str) else source,
            writable,
        )
        for target, (kind, source, writable) in actual.items()
    }
    same_mounts = actual == expected or (sys.platform == "darwin" and desktop_actual == expected)
    if record.get("Config", {}).get("Image") != IMAGE or len(mounts) != len(expected) or not same_mounts:
        raise ValueError("DEV_VERIFICATION_WORKTREE_OR_DEPENDENCIES_REFUSED")
    declared = record.get("HostConfig", {}).get("Mounts", [])
    subpaths = {
        mount.get("Target"): (mount.get("Source"), mount.get("ImageOptions", {}).get("Subpath"))
        for mount in declared
        if mount.get("Type") == "image"
    }
    if subpaths != {
        target: (image_id, target.removeprefix("/")) for target, (kind, _, _) in expected.items() if kind == "image"
    }:
        raise ValueError("DEV_VERIFICATION_DEPENDENCY_SUBPATH_REFUSED")
    postgres = [
        entry for entry in record.get("Config", {}).get("Env", []) if entry.startswith("ONLYALPHA_POSTGRES_DSN=")
    ]
    if postgres != [
        "ONLYALPHA_POSTGRES_DSN=postgresql://onlyalpha:onlyalpha@postgres:5432/onlyalpha_dev_validation_test"
    ]:
        raise ValueError("DEV_VERIFICATION_DATABASE_REFUSED")


def run_inside(command: list[str], *, web: bool = False, operation_id: str = "") -> int:
    if not command:
        raise ValueError("DEV_VERIFICATION_COMMAND_REQUIRED")
    with CONTAINER_LOCK.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("DEV_VERIFICATION_BUSY") from error
        if (ROOT / BROWSER_RESET_FENCE).exists():
            raise ValueError("DEV_VERIFICATION_BROWSER_RESET_UNKNOWN")
        admitted = json.loads(ENVIRONMENT_RECORD.read_text())
        if environment_inputs(ROOT) != admitted:
            raise ValueError("DEV_VERIFICATION_ENVIRONMENT_REBUILD_REQUIRED")
        before = source_inputs(ROOT)
        source_cut = json.loads((ROOT / CUT_METADATA).read_text())
        if (
            source_cut.get("operation_id") != operation_id
            or source_cut.get("inputs") != before
            or source_cut.get("source_root") != os.environ.get("ONLYALPHA_DEV_SOURCE_ROOT", str(ROOT))
            or source_cut.get("git_inputs", {}) != git_input_hashes(ROOT)
        ):
            raise ValueError("DEV_VERIFICATION_SOURCE_CUT_NOT_ADMITTED")
        artifacts = ROOT / "test-results/dev-verification"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "source-inputs.json").write_text(json.dumps(before, sort_keys=True, indent=2))
        digest = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
        print("DEV_VERIFICATION_SOURCE_SHA256", digest, flush=True)
        # Database creation and the canonical _test guard remain in compose_test.
        # That process inherits the lock so a killed launcher cannot admit a
        # second suite while its first child is still using mutable test state.
        os.set_inheritable(lock.fileno(), True)
        environment = {
            **os.environ,
            "ONLYALPHA_DEV_VERIFICATION_LOCK_FD": str(lock.fileno()),
            "ONLYALPHA_DEV_VERIFICATION_OPERATION_ID": operation_id,
        }
        child = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/compose_test.py"), *command],
            cwd=ROOT / WEB if web else ROOT,
            pass_fds=(lock.fileno(),),
            env=environment,
            start_new_session=True,
        )

        def forward(number: int, _frame: object) -> None:
            try:
                os.killpg(child.pid, number)
            except ProcessLookupError:
                pass

        previous = {number: signal.signal(number, forward) for number in (signal.SIGINT, signal.SIGTERM)}
        try:
            status = child.wait()
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
        after = source_inputs(ROOT)
        changed = before != after
        reset_unknown = (ROOT / BROWSER_RESET_FENCE).exists()
        (artifacts / "last-outcome.json").write_text(
            json.dumps(
                {
                    "source_sha256": digest,
                    "command_exit": status,
                    "operation_id": operation_id,
                    "completed": status >= 0 and not reset_unknown,
                    "browser_reset_unknown": reset_unknown,
                    "source_changed_during_verification": changed,
                },
                indent=2,
            )
        )
        if changed:
            raise ValueError("DEV_VERIFICATION_SOURCE_CHANGED")
        return status if status >= 0 else 128 - status


def run_host(mode: str, command: list[str], *, web: bool, rebuild: bool, reservation: dict[str, Any]) -> int:
    # Early refusals have no outstanding command. Once an operation is submitted,
    # only an observed completion/owning worker receipt can settle this fence.
    reservation["completed"] = True
    if (ROOT / BROWSER_RESET_FENCE).exists():
        reservation["completed"] = False
        raise ValueError("DEV_VERIFICATION_BROWSER_RESET_UNKNOWN")
    if os.environ.get("ONLYALPHA_COMPOSE_NAMESPACE", "onlyalpha-dev") != "onlyalpha-dev":
        raise ValueError("DEV_VERIFICATION_PROJECT_REFUSED")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("ONLYALPHA_")}
    environment["ONLYALPHA_COMPOSE_NAMESPACE"] = "onlyalpha-dev"
    compose = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        "onlyalpha-dev",
        "-f",
        str(ROOT / "deploy/docker-compose.dev.yml"),
        "--profile",
        "test",
    ]
    ids = subprocess.check_output(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.docker.compose.project=onlyalpha-dev",
            "--filter",
            "label=com.docker.compose.service=validation",
        ],
        text=True,
        timeout=15,
    ).split()
    if ids:
        records = json.loads(subprocess.check_output(["docker", "inspect", *ids], text=True, timeout=15))
        if len(records) != 1:
            raise ValueError("DEV_VERIFICATION_WORKTREE_REFUSED")
        validate_container(records[0], ROOT)
        if records[0].get("State", {}).get("Running") is True:
            # A killed host launcher may leave its lock-holding test child alive.
            # Never rebuild/recreate that service underneath retained work.
            reservation["completed"] = False
            probe = subprocess.run(
                [
                    "docker",
                    "exec",
                    records[0]["Id"],
                    "python",
                    "-c",
                    "import fcntl; from pathlib import Path; "
                    f"lock=Path({str(CONTAINER_LOCK)!r}).open('a'); "
                    "fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
            )
            if probe.returncode:
                raise ValueError("DEV_VERIFICATION_PREPARATION_NOT_ADMITTED")
            reservation["completed"] = True
        if mode == "run":
            if records[0].get("State", {}).get("Running") is not True:
                raise ValueError("DEV_VERIFICATION_CONTAINER_NOT_RUNNING")
            artifacts = ROOT / "test-results/dev-verification"
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / "container-inputs.json").write_text(
                json.dumps(
                    {
                        "container_id": records[0]["Id"],
                        "image_id": records[0]["Image"],
                        "mounts": records[0]["Mounts"],
                    },
                    indent=2,
                )
            )
    elif mode == "run":
        raise ValueError("DEV_VERIFICATION_CONTAINER_REQUIRED")
    inputs = freeze_source(ROOT, reservation["operation_id"], research="research-postgres" in command)
    if mode == "prepare":
        # Explicit setup/rebuild only. Ordinary run never invokes build/up/run/down.
        available = (
            subprocess.run(
                ["docker", "image", "inspect", IMAGE],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
            ).returncode
            == 0
        )
        reservation["completed"] = False
        if rebuild or not available:
            subprocess.run([*compose, "build", "validation"], cwd=ROOT, env=environment, check=True)
        image = json.loads(subprocess.check_output(["docker", "image", "inspect", IMAGE], text=True, timeout=15))[0]
        environment["ONLYALPHA_DEV_TOOL_IMAGE_ID"] = image["Id"]
        subprocess.run(
            [*compose, "up", "-d", "--no-build", "--pull", "never", "--wait", "postgres", "clickhouse", "validation"],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        reservation["completed"] = True
        return 0
    if not command:
        raise ValueError("DEV_VERIFICATION_COMMAND_REQUIRED")
    invocation = [
        *compose,
        "exec",
        "-T",
        "--interactive=false",
        "-e",
        f"ONLYALPHA_DEV_SOURCE_ROOT={ROOT}",
        "validation",
        "python",
        "scripts/dev_verification.py",
    ]
    invocation += ["--operation-id", reservation["operation_id"]]
    if web:
        invocation.append("--web")
    invocation += ["inside", "--", *command]
    reservation["completed"] = False
    status = subprocess.run(invocation, cwd=ROOT, env=environment, check=False).returncode
    outcome = json.loads((ROOT / "test-results/dev-verification/last-outcome.json").read_text())
    if outcome.get("operation_id") != reservation["operation_id"] or outcome.get("completed") is not True:
        raise ValueError("DEV_VERIFICATION_COMMAND_COMPLETION_UNPROVEN")
    reservation["completed"] = True
    if source_inputs(ROOT) != inputs:
        raise ValueError("DEV_VERIFICATION_CURRENT_SOURCE_DIFFERS_FROM_VERIFIED_CUT")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run", "inside"))
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--operation-id", default="")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.mode == "inside":
        # This receipt is emitted only for pre-command admission refusal; errors
        # after command startup must leave completion UNKNOWN.
        artifacts = ROOT / "test-results/dev-verification"
        artifacts.mkdir(parents=True, exist_ok=True)
        try:
            return run_inside(command, web=args.web, operation_id=args.operation_id)
        except ValueError as error:
            if str(error) in {
                "DEV_VERIFICATION_COMMAND_REQUIRED",
                "DEV_VERIFICATION_BUSY",
                "DEV_VERIFICATION_ENVIRONMENT_REBUILD_REQUIRED",
                "DEV_VERIFICATION_SOURCE_CUT_NOT_ADMITTED",
            }:
                (artifacts / "last-outcome.json").write_text(
                    json.dumps(
                        {
                            "operation_id": args.operation_id,
                            "completed": True,
                            "command_started": False,
                            "refusal": str(error),
                        }
                    )
                )
            raise
    with host_operation(ROOT, args.mode) as reservation:
        return run_host(args.mode, command, web=args.web, rebuild=args.rebuild, reservation=reservation)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
