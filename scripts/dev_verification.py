"""Reusable source-mounted verification in the sole local dev Compose project."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import signal
import stat
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
CONTROLLED_HOSTS = Path("/etc/hosts")
CONTROLLED_HOSTNAME = b"data-api.binance.vision"
CONTROLLED_HOSTS_BACKUPS = Path("/root/onlyalpha-dev-controlled-https")
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
    paths = [
        root / name
        for name in ("pyproject.toml", "uv.lock", "deploy/Dockerfile.dev", "deploy/Dockerfile.dev.dockerignore")
    ]
    paths += [root / WEB / name for name in ("package.json", "package-lock.json")]
    paths += [root / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml") if (root / name).is_file()]
    paths += sorted((root / "crates").rglob("Cargo.toml"))
    paths += sorted((root / "packages").glob("*/Cargo.toml"))
    paths += sorted((root / "plugs").glob("*/Cargo.toml"))
    for directory in ("packages", "plugs"):
        paths += sorted((root / directory).glob("*/pyproject.toml"))
    paths += sorted((root / "packages/backend/python").glob("*/pyproject.toml"))
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
        mode = source.stat().st_mode & 0o555
        # The whole previous cut was verified above. Reuse its bytes and mtime
        # only after that guard; final inventories still detect live changes.
        if previous.get("inputs", {}).get(name) == digest and target.stat().st_mode & 0o777 == mode:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".dev-copy")
        shutil.copyfile(source, temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            temporary.unlink()
            raise ValueError("DEV_VERIFICATION_SOURCE_CHANGED_DURING_CAPTURE")
        temporary.chmod(mode)
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


def controlled_https_command(command: list[str]) -> bool:
    return (
        command[:3] == ["python", "-m", "scripts.native_web_e2e"]
        and command.count("--controlled-source-https") == 1
        and command.count("--retained-market-input") == 1
    )


def controlled_hosts_bytes(original: bytes, operation_id: str) -> bytes:
    if str(uuid.UUID(operation_id)) != operation_id or uuid.UUID(operation_id).version != 4:
        raise ValueError("DEV_CONTROLLED_HTTPS_OPERATION_INVALID")
    if b"onlyalpha-dev-controlled-https:" in original or CONTROLLED_HOSTNAME in original.lower():
        raise ValueError("DEV_CONTROLLED_HTTPS_EXISTING_MAPPING_REFUSED")
    newline = b"" if original.endswith(b"\n") else b"\n"
    return (
        original
        + newline
        + b"127.0.0.1 "
        + CONTROLLED_HOSTNAME
        + b" # onlyalpha-dev-controlled-https:"
        + operation_id.encode("ascii")
        + b"\n"
    )


def _root_record(directory: Path, name: str, raw: bytes) -> None:
    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _root_read(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        observed = os.fstat(stream.fileno())
        if not stat.S_ISREG(observed.st_mode) or observed.st_uid != 0 or observed.st_nlink != 1:
            raise ValueError("DEV_CONTROLLED_HTTPS_BACKUP_INVALID")
        return stream.read(1024 * 1024 + 1)


def _root_directory(path: Path, *, fresh: bool) -> None:
    if fresh:
        path.mkdir(mode=0o700)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    observed = path.lstat()
    if not stat.S_ISDIR(observed.st_mode) or observed.st_uid != 0 or stat.S_IMODE(observed.st_mode) != 0o700:
        raise ValueError("DEV_CONTROLLED_HTTPS_BACKUP_INVALID")


def validate_controlled_proof(proof: Any, operation_id: str, action: str) -> dict[str, Any]:
    if (
        str(uuid.UUID(operation_id)) != operation_id
        or uuid.UUID(operation_id).version != 4
        or action not in {"begin", "restore"}
    ):
        raise ValueError("DEV_CONTROLLED_HTTPS_RESOURCE_COMPLETION_UNPROVEN")
    fields = {"operation_id", "device", "inode", "original_sha256", "mapped_sha256", "action", "completed"}
    if (
        not isinstance(proof, dict)
        or set(proof) != fields
        or proof["operation_id"] != operation_id
        or proof["action"] != action
        or proof["completed"] is not True
        or type(proof["device"]) is not int
        or proof["device"] < 0
        or type(proof["inode"]) is not int
        or proof["inode"] <= 0
        or any(
            not isinstance(proof[key], str)
            or len(proof[key]) != 64
            or any(c not in "0123456789abcdef" for c in proof[key])
            for key in ("original_sha256", "mapped_sha256")
        )
    ):
        raise ValueError("DEV_CONTROLLED_HTTPS_RESOURCE_COMPLETION_UNPROVEN")
    return proof


def controlled_https_root(action: str, operation_id: str) -> dict[str, Any]:
    """Fixed resource lifecycle only; no command, path, credential or key argument."""
    if os.geteuid() != 0 or ROOT != Path("/workspace") or action not in {"begin", "restore"}:
        raise ValueError("DEV_CONTROLLED_HTTPS_ROOT_REQUIRED")
    if str(uuid.UUID(operation_id)) != operation_id or uuid.UUID(operation_id).version != 4:
        raise ValueError("DEV_CONTROLLED_HTTPS_OPERATION_INVALID")
    marker_fd = os.open(ROOT / CUT_METADATA, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(marker_fd) as marker:
        if json.load(marker).get("operation_id") != operation_id:
            raise ValueError("DEV_CONTROLLED_HTTPS_SOURCE_CUT_REFUSED")
    # This must already be the ordinary uid10001 lock. Never create a root-owned lock.
    lock_fd = os.open(CONTAINER_LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(lock_fd, "rb") as lock:
        observed = os.fstat(lock.fileno())
        if not stat.S_ISREG(observed.st_mode) or observed.st_uid != 10001 or observed.st_nlink != 1:
            raise ValueError("DEV_CONTROLLED_HTTPS_LOCK_REFUSED")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            _root_directory(CONTROLLED_HOSTS_BACKUPS, fresh=False)
        except FileNotFoundError:
            if action != "begin":
                raise
            _root_directory(CONTROLLED_HOSTS_BACKUPS, fresh=True)
        backup = CONTROLLED_HOSTS_BACKUPS / operation_id
        _root_directory(backup, fresh=action == "begin")
        fd = os.open(CONTROLLED_HOSTS, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, "r+b", buffering=0) as hosts:
            identity = os.fstat(hosts.fileno())
            if (
                not stat.S_ISREG(identity.st_mode)
                or identity.st_uid != 0
                or identity.st_nlink != 1
                or identity.st_mode & 0o022
            ):
                raise ValueError("DEV_CONTROLLED_HTTPS_HOSTS_REFUSED")
            current = hosts.read(1024 * 1024 + 1)
            if len(current) > 1024 * 1024:
                raise ValueError("DEV_CONTROLLED_HTTPS_HOSTS_REFUSED")

            def sha(raw: bytes) -> str:
                return hashlib.sha256(raw).hexdigest()

            if action == "begin":
                mapped = controlled_hosts_bytes(current, operation_id)
                evidence = {
                    "operation_id": operation_id,
                    "device": identity.st_dev,
                    "inode": identity.st_ino,
                    "original_sha256": sha(current),
                    "mapped_sha256": sha(mapped),
                }
                _root_record(backup, "original", current)
                _root_record(backup, "begin.json", json.dumps(evidence, sort_keys=True).encode())
                target = mapped
            else:
                evidence = json.loads(_root_read(backup / "begin.json"))
                validate_controlled_proof({**evidence, "action": "begin", "completed": True}, operation_id, "begin")
                original = _root_read(backup / "original")
                if (
                    evidence.get("operation_id") != operation_id
                    or evidence.get("device") != identity.st_dev
                    or evidence.get("inode") != identity.st_ino
                    or evidence.get("original_sha256") != sha(original)
                ):
                    raise ValueError("DEV_CONTROLLED_HTTPS_RESTORE_IDENTITY_REFUSED")
                mapped = controlled_hosts_bytes(original, operation_id)
                if evidence.get("mapped_sha256") != sha(mapped):
                    raise ValueError("DEV_CONTROLLED_HTTPS_RESTORE_CAS_REFUSED")
                try:
                    replay = json.loads(_root_read(backup / "restore-proof.json"))
                except FileNotFoundError:
                    replay = None
                if replay is not None:
                    replay = validate_controlled_proof(replay, operation_id, "restore")
                    if current != original or any(replay[key] != evidence[key] for key in evidence):
                        raise ValueError("DEV_CONTROLLED_HTTPS_RESTORE_CAS_REFUSED")
                    rebound = os.stat(CONTROLLED_HOSTS, follow_symlinks=False)
                    if (rebound.st_dev, rebound.st_ino) != (identity.st_dev, identity.st_ino):
                        raise ValueError("DEV_CONTROLLED_HTTPS_RESTORE_IDENTITY_REFUSED")
                    return replay
                if current != mapped:
                    # Original bytes without a completed proof can be an interrupted/partial action.
                    raise ValueError("DEV_CONTROLLED_HTTPS_RESTORE_CAS_REFUSED")
                target = original
            # Docker owns this mounted inode: restore exact bytes in place, never replace it.
            offset = 0
            while offset < len(target):
                written = os.pwrite(hosts.fileno(), target[offset:], offset)
                if written <= 0:
                    raise ValueError("DEV_CONTROLLED_HTTPS_WRITE_UNPROVEN")
                offset += written
            os.ftruncate(hosts.fileno(), len(target))
            os.fsync(hosts.fileno())
            hosts.seek(0)
            path_identity = os.stat(CONTROLLED_HOSTS, follow_symlinks=False)
            if hosts.read() != target or (path_identity.st_dev, path_identity.st_ino) != (
                identity.st_dev,
                identity.st_ino,
            ):
                raise ValueError("DEV_CONTROLLED_HTTPS_WRITE_UNPROVEN")
            proof = {**evidence, "action": action, "completed": True}
            _root_record(backup, action + "-proof.json", json.dumps(proof, sort_keys=True).encode())
            return proof


def controlled_https_mapping(raw: bytes, operation_id: str) -> bool:
    line = b"127.0.0.1 " + CONTROLLED_HOSTNAME + b" # onlyalpha-dev-controlled-https:" + operation_id.encode("ascii")
    aliases = [
        entry
        for entry in raw.splitlines()
        if CONTROLLED_HOSTNAME in [name.lower() for name in entry.split(b"#", 1)[0].split()[1:]]
    ]
    return len(raw) <= 1024 * 1024 and raw.count(b"onlyalpha-dev-controlled-https:") == 1 and aliases == [line]


def _controlled_https_exec(
    container: dict[str, Any], operation_id: str, source_sha256: str, action: str, environment: dict[str, str]
) -> dict[str, Any]:
    container_id = container["Id"]
    image_id = container["Image"]
    if (
        not isinstance(container_id, str)
        or len(container_id) != 64
        or any(c not in "0123456789abcdef" for c in container_id)
        or not isinstance(image_id, str)
        or len(image_id) != 71
        or not image_id.startswith("sha256:")
        or any(c not in "0123456789abcdef" for c in image_id[7:])
        or len(source_sha256) != 64
        or any(c not in "0123456789abcdef" for c in source_sha256)
    ):
        raise ValueError("DEV_CONTROLLED_HTTPS_CONTAINER_REFUSED")
    raw = subprocess.check_output(
        [
            "docker",
            "exec",
            "--user",
            "0",
            container_id,
            "python",
            "/workspace/scripts/dev_verification.py",
            "--operation-id",
            operation_id,
            "controlled-https-" + action,
        ],
        env=environment,
        text=True,
        timeout=15,
    )
    proof = validate_controlled_proof(json.loads(raw), operation_id, action)
    receipt = {**proof, "container_id": container_id, "image_id": container["Image"], "source_sha256": source_sha256}
    path = ROOT / "test-results/dev-verification" / (operation_id + "-controlled-https-" + action + ".json")
    document = json.dumps(receipt, sort_keys=True).encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            if stream.read() != document:
                raise ValueError("DEV_CONTROLLED_HTTPS_RECEIPT_CONFLICT") from None
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return receipt


def run_inside(
    command: list[str], *, web: bool = False, operation_id: str = "", controlled_source_https: bool = False
) -> int:
    if not command:
        raise ValueError("DEV_VERIFICATION_COMMAND_REQUIRED")
    if (
        controlled_source_https != ("--controlled-source-https" in command)
        or controlled_source_https
        and (web or os.geteuid() != 10001 or not controlled_https_command(command))
    ):
        raise ValueError("DEV_CONTROLLED_HTTPS_COMMAND_REFUSED")
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
        if controlled_source_https:
            hosts_fd = os.open(CONTROLLED_HOSTS, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(hosts_fd, "rb") as hosts:
                identity = os.fstat(hosts.fileno())
                if (
                    not stat.S_ISREG(identity.st_mode)
                    or identity.st_uid != 0
                    or identity.st_nlink != 1
                    or identity.st_mode & 0o022
                    or not controlled_https_mapping(hosts.read(1024 * 1024 + 1), operation_id)
                ):
                    raise ValueError("DEV_CONTROLLED_HTTPS_MAPPING_UNPROVEN")
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


def run_host(
    mode: str,
    command: list[str],
    *,
    web: bool,
    rebuild: bool,
    reservation: dict[str, Any],
    controlled_source_https: bool = False,
) -> int:
    # Early refusals have no outstanding command. Once an operation is submitted,
    # only an observed completion/owning worker receipt can settle this fence.
    reservation["completed"] = True
    if (
        controlled_source_https != ("--controlled-source-https" in command)
        or controlled_source_https
        and (mode != "run" or web or rebuild or not controlled_https_command(command))
    ):
        raise ValueError("DEV_CONTROLLED_HTTPS_COMMAND_REFUSED")
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
    if mode == "runtime-build":
        from scripts.runtime_build import build_image

        if web or rebuild:
            raise ValueError("RUNTIME_BUILD_OPTIONS_REFUSED")
        return build_image(ROOT, command, reservation)
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
    if controlled_source_https:
        invocation.append("--controlled-source-https")
    invocation += ["inside", "--", *command]
    reservation["completed"] = False
    begin = None
    if controlled_source_https:
        cut = json.loads((ROOT / ".test-cache/dev-source-cut" / CUT_METADATA).read_text())
        if cut.get("operation_id") != reservation["operation_id"]:
            raise ValueError("DEV_CONTROLLED_HTTPS_SOURCE_CUT_REFUSED")
        source_sha256 = hashlib.sha256(json.dumps(cut["inputs"], sort_keys=True).encode()).hexdigest()
        begin = _controlled_https_exec(records[0], reservation["operation_id"], source_sha256, "begin", environment)
    status = subprocess.run(invocation, cwd=ROOT, env=environment, check=False).returncode
    outcome = json.loads((ROOT / "test-results/dev-verification/last-outcome.json").read_text())
    if outcome.get("operation_id") != reservation["operation_id"] or outcome.get("completed") is not True:
        raise ValueError("DEV_VERIFICATION_COMMAND_COMPLETION_UNPROVEN")
    if controlled_source_https:
        if begin is None or (
            outcome.get("command_started") is not False and outcome.get("source_sha256") != begin["source_sha256"]
        ):
            raise ValueError("DEV_CONTROLLED_HTTPS_SOURCE_COMPLETION_UNPROVEN")
        current = json.loads(subprocess.check_output(["docker", "inspect", records[0]["Id"]], text=True, timeout=15))
        if len(current) != 1:
            raise ValueError("DEV_CONTROLLED_HTTPS_CONTAINER_REFUSED")
        validate_container(current[0], ROOT)
        if (
            current[0].get("Id") != begin["container_id"]
            or current[0].get("Image") != begin["image_id"]
            or current[0].get("State", {}).get("Running") is not True
        ):
            raise ValueError("DEV_CONTROLLED_HTTPS_CONTAINER_REFUSED")
        restored = _controlled_https_exec(
            current[0], reservation["operation_id"], begin["source_sha256"], "restore", environment
        )
        if any(
            restored.get(key) != begin.get(key)
            for key in (
                "container_id",
                "image_id",
                "source_sha256",
                "device",
                "inode",
                "original_sha256",
                "mapped_sha256",
            )
        ):
            raise ValueError("DEV_CONTROLLED_HTTPS_RESOURCE_COMPLETION_UNPROVEN")
    reservation["completed"] = True
    if source_inputs(ROOT) != inputs:
        raise ValueError("DEV_VERIFICATION_CURRENT_SOURCE_DIFFERS_FROM_VERIFIED_CUT")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=("prepare", "run", "inside", "runtime-build", "controlled-https-begin", "controlled-https-restore"),
    )
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--operation-id", default="")
    parser.add_argument("--controlled-source-https", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.mode in {"controlled-https-begin", "controlled-https-restore"}:
        if command or args.web or args.rebuild or args.controlled_source_https:
            raise ValueError("DEV_CONTROLLED_HTTPS_COMMAND_REFUSED")
        print(
            json.dumps(
                controlled_https_root(args.mode.removeprefix("controlled-https-"), args.operation_id), sort_keys=True
            ),
            flush=True,
        )
        return 0
    if args.mode == "inside":
        # This receipt is emitted only for pre-command admission refusal; errors
        # after command startup must leave completion UNKNOWN.
        artifacts = ROOT / "test-results/dev-verification"
        artifacts.mkdir(parents=True, exist_ok=True)
        try:
            return run_inside(
                command,
                web=args.web,
                operation_id=args.operation_id,
                controlled_source_https=args.controlled_source_https,
            )
        except ValueError as error:
            if str(error) in {
                "DEV_VERIFICATION_COMMAND_REQUIRED",
                "DEV_VERIFICATION_BUSY",
                "DEV_VERIFICATION_ENVIRONMENT_REBUILD_REQUIRED",
                "DEV_VERIFICATION_SOURCE_CUT_NOT_ADMITTED",
                "DEV_CONTROLLED_HTTPS_COMMAND_REFUSED",
                "DEV_CONTROLLED_HTTPS_MAPPING_UNPROVEN",
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
        return run_host(
            args.mode,
            command,
            web=args.web,
            rebuild=args.rebuild,
            reservation=reservation,
            controlled_source_https=args.controlled_source_https,
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
