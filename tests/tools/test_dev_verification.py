from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import dev_verification, embed_build_provenance
from scripts.embed_build_provenance import resolve_build_provenance_bytes


def _environment(root: Path) -> None:
    for name in (
        "pyproject.toml",
        "uv.lock",
        "deploy/Dockerfile.dev",
        "deploy/Dockerfile.dev.dockerignore",
        "packages/frontend/package.json",
        "packages/frontend/package-lock.json",
        "plugs/example/pyproject.toml",
        "test-data/external_plugins/onlyalpha_test_plugin/pyproject.toml",
        "test-data/runtime_factor_provider/pyproject.toml",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("input")


def test_runtime_image_build_uses_existing_admitted_host_lifecycle(monkeypatch, tmp_path: Path) -> None:
    from scripts import runtime_build

    calls = _host(monkeypatch, tmp_path, ["runtime-build", "--", "--release-inputs", "selected.json"])
    observed = []
    monkeypatch.setattr(
        runtime_build, "build_image", lambda root, command, owner: observed.append((root, command, owner)) or 0
    )
    assert dev_verification.main() == 0
    assert observed[0][0] == tmp_path
    assert observed[0][1] == ["--release-inputs", "selected.json"]
    assert not any("build" in command or "up" in command for command, _ in calls)


@pytest.mark.parametrize("product", [False, True])
def test_freeze_reuses_verified_unchanged_source_without_touching_build_inputs(tmp_path: Path, product: bool) -> None:
    _environment(tmp_path)
    dev_verification.freeze_source(tmp_path, "first", product=product)
    cut = tmp_path / (".test-cache/dev-product-source" if product else ".test-cache/dev-source-cut")
    target = cut / "pyproject.toml"
    os.utime(target, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    before = target.stat()
    dev_verification.freeze_source(tmp_path, "unchanged", product=product)
    assert (target.stat().st_ino, target.stat().st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert target.stat().st_mode & 0o777 == 0o444
    (tmp_path / "pyproject.toml").write_text("changed")
    dev_verification.freeze_source(tmp_path, "changed", product=product)
    assert target.read_text() == "changed"
    (tmp_path / "pyproject.toml").chmod(0o755)
    dev_verification.freeze_source(tmp_path, "executable", product=product)
    assert target.stat().st_mode & 0o777 == 0o555


def test_freeze_cache_still_rejects_tampering_and_concurrent_source_changes(tmp_path: Path, monkeypatch) -> None:
    _environment(tmp_path)
    dev_verification.freeze_source(tmp_path, "first", product=True)
    target = tmp_path / ".test-cache/dev-product-source/pyproject.toml"
    target.chmod(0o644)
    target.write_text("tampered")
    with pytest.raises(ValueError, match="SOURCE_CUT_MODIFIED"):
        dev_verification.freeze_source(tmp_path, "tampered", product=True)
    target.write_text("input")
    original = dev_verification.source_inputs
    calls = 0

    def mutate_after_inventory(root: Path) -> dict[str, str]:
        nonlocal calls
        result = original(root)
        if root == tmp_path:
            calls += 1
            if calls == 1:
                (root / "pyproject.toml").write_text("concurrent change")
        return result

    monkeypatch.setattr(dev_verification, "source_inputs", mutate_after_inventory)
    with pytest.raises(ValueError, match="SOURCE_CHANGED_DURING_CAPTURE"):
        dev_verification.freeze_source(tmp_path, "concurrent", product=True)


def test_source_edits_reuse_environment_but_dependency_edits_require_rebuild(tmp_path: Path) -> None:
    _environment(tmp_path)
    admitted = dev_verification.environment_inputs(tmp_path)
    source = tmp_path / "scripts/example.py"
    source.parent.mkdir()
    source.write_text("changed source")
    assert dev_verification.environment_inputs(tmp_path) == admitted
    (tmp_path / "uv.lock").write_text("changed dependency")
    assert dev_verification.environment_inputs(tmp_path) != admitted


def test_backend_python_constituents_are_environment_inputs(tmp_path: Path) -> None:
    _environment(tmp_path)
    path = tmp_path / "packages/backend/python/algorithms/pyproject.toml"
    path.parent.mkdir(parents=True)
    path.write_text("first metadata")
    before = dev_verification.environment_inputs(tmp_path)
    assert str(path.relative_to(tmp_path)) in before
    path.write_text("changed dependency")
    assert dev_verification.environment_inputs(tmp_path) != before


def test_docker_context_filter_changes_require_environment_rebuild(tmp_path: Path) -> None:
    _environment(tmp_path)
    before = dev_verification.environment_inputs(tmp_path)
    (tmp_path / "deploy/Dockerfile.dev.dockerignore").write_text("changed build context rules")
    assert dev_verification.environment_inputs(tmp_path) != before


def test_source_inventory_excludes_artifacts_and_host_dependencies(tmp_path: Path) -> None:
    _environment(tmp_path)
    before = dev_verification.source_inputs(tmp_path)
    for directory in ("test-results", ".venv", "packages/frontend/node_modules", "target"):
        path = tmp_path / directory
        path.mkdir(parents=True, exist_ok=True)
        (path / "generated").write_text("not source")
    assert dev_verification.source_inputs(tmp_path) == before
    (tmp_path / "pyproject.toml").write_text("source change")
    assert dev_verification.source_inputs(tmp_path) != before


@pytest.mark.parametrize("name", ["env", "venv"])
@pytest.mark.parametrize("product", [False, True])
def test_root_host_environments_never_enter_frozen_source(tmp_path: Path, name: str, product: bool) -> None:
    _environment(tmp_path)
    before = dev_verification.source_inputs(tmp_path)
    environment = tmp_path / name / "host-python"
    (environment / "bin").mkdir(parents=True)
    (environment / "pyvenv.cfg").write_text("controlled host dependency")
    (environment / "bin/python").symlink_to("/unavailable/host/python")
    assert dev_verification.source_inputs(tmp_path) == before
    assert dev_verification.freeze_source(tmp_path, "host-environment-isolation", product=product) == before
    cut = tmp_path / (".test-cache/dev-product-source" if product else ".test-cache/dev-source-cut")
    assert not (cut / name).exists()
    assert (environment / "bin/python").is_symlink()
    assert (environment / "pyvenv.cfg").read_text() == "controlled host dependency"


@pytest.mark.parametrize("name", ["env", "venv"])
def test_nested_environment_named_source_remains_part_of_frozen_input(tmp_path: Path, name: str) -> None:
    _environment(tmp_path)
    source = tmp_path / "packages/example" / name / "configuration.py"
    source.parent.mkdir(parents=True)
    source.write_text("initial source")
    before = dev_verification.source_inputs(tmp_path)
    assert source.relative_to(tmp_path).as_posix() in before
    source.write_text("changed source")
    assert dev_verification.source_inputs(tmp_path) != before
    (source.parent / "alias.py").symlink_to(source)
    with pytest.raises(ValueError, match="SOURCE_SYMLINK"):
        dev_verification.source_inputs(tmp_path)


@pytest.mark.parametrize("directory", [False, True])
def test_source_inventory_refuses_symlinks(tmp_path: Path, directory: bool) -> None:
    target = tmp_path / "unknown"
    if directory:
        target.mkdir()
    (tmp_path / "alias.py").symlink_to(target, target_is_directory=directory)
    with pytest.raises(ValueError, match="SOURCE_SYMLINK"):
        dev_verification.source_inputs(tmp_path)


@pytest.mark.parametrize("product", [False, True])
def test_local_runtime_data_and_secrets_never_enter_frozen_source(tmp_path: Path, product: bool) -> None:
    _environment(tmp_path)
    before = dev_verification.source_inputs(tmp_path)
    runtime = tmp_path / "user_data"
    (runtime / "secrets").mkdir(parents=True)
    (runtime / "secrets/dev-master-key").write_bytes(b"controlled-test-key-not-a-credential")
    (runtime / "research").mkdir()
    (runtime / "research/history.json").write_text("controlled-test-history")
    assert dev_verification.source_inputs(tmp_path) == before
    inputs = dev_verification.freeze_source(tmp_path, "runtime-isolation", product=product)
    cut = tmp_path / (".test-cache/dev-product-source" if product else ".test-cache/dev-source-cut")
    assert inputs == before
    assert not (cut / "user_data").exists()
    (runtime / "research/history.json").write_text("later-history")
    assert dev_verification.source_inputs(tmp_path) == before
    assert (runtime / "secrets/dev-master-key").read_bytes() == b"controlled-test-key-not-a-credential"


def test_product_and_verification_source_views_never_refresh_each_other(tmp_path: Path) -> None:
    _environment(tmp_path)
    before = dev_verification.freeze_source(tmp_path, "application", product=True)
    product = tmp_path / ".test-cache/dev-product-source"
    assert not (product / ".git").exists()
    assert json.loads((product / dev_verification.CUT_METADATA).read_text())["git_inputs"] == {}
    (tmp_path / "pyproject.toml").write_text("later verification source")
    dev_verification.freeze_source(tmp_path, "verification")
    assert dev_verification.source_inputs(product) == before
    assert (product / "pyproject.toml").read_text() == "input"
    assert (tmp_path / ".test-cache/dev-source-cut/pyproject.toml").read_text() == "later verification source"


@pytest.mark.parametrize("product", [False, True])
def test_freezing_source_preserves_existing_typescript_incremental_state(tmp_path: Path, product: bool) -> None:
    _environment(tmp_path)
    dev_verification.freeze_source(tmp_path, "before-build", product=product)
    cut = tmp_path / (".test-cache/dev-product-source" if product else ".test-cache/dev-source-cut")
    output = tmp_path / ".test-cache/dev-tool-output"
    original = {}
    for directory in (cut / dev_verification.WEB, output):
        for name in ("tsconfig.app.tsbuildinfo", "tsconfig.node.tsbuildinfo"):
            path = directory / name
            assert path.is_file()
            path.write_text("controlled incremental build state")
            os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
            original[path] = (path.read_bytes(), path.stat().st_mtime_ns)

    dev_verification.freeze_source(tmp_path, "after-build", product=product)

    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in original} == original


def _host(monkeypatch, tmp_path: Path, arguments: list[str], *, present: bool = True):
    calls = []
    _environment(tmp_path)
    monkeypatch.setattr(dev_verification, "ROOT", tmp_path)
    monkeypatch.setattr(dev_verification, "HOST_STATE", tmp_path.parent / (tmp_path.name + "-host-state"))
    monkeypatch.setattr(sys, "argv", ["dev_verification.py", *arguments])
    monkeypatch.delenv("ONLYALPHA_COMPOSE_NAMESPACE", raising=False)
    record = _container(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda command, **k: (
            json.dumps([{"Id": record["Image"]}])
            if command[:3] == ["docker", "image", "inspect"]
            else (("container" if "ps" in command else json.dumps([record])) if "run" in arguments else "")
        ),
    )

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "--operation-id" in command:
            artifacts = tmp_path / "test-results/dev-verification"
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / "last-outcome.json").write_text(
                json.dumps(
                    {
                        "operation_id": command[command.index("--operation-id") + 1],
                        "completed": True,
                    }
                )
            )
        return SimpleNamespace(returncode=(0 if present else 1) if command[:3] == ["docker", "image", "inspect"] else 0)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def _container(root: Path):
    dependencies = [
        "/workspace/.venv",
        "/workspace/packages/frontend/node_modules",
        "/usr/local/rustup",
        "/usr/local/cargo",
    ]
    return {
        "Id": "container",
        "Image": "sha256:" + "a" * 64,
        "State": {"Running": True},
        "Config": {
            "Image": dev_verification.IMAGE,
            "Env": [
                "ONLYALPHA_POSTGRES_DSN=postgresql://onlyalpha:onlyalpha@postgres:5432/onlyalpha_dev_validation_test",
            ],
        },
        "Mounts": [
            {
                "Type": "bind",
                "Destination": "/workspace",
                "Source": str(root / ".test-cache/dev-source-cut"),
                "RW": False,
            },
            {"Type": "bind", "Destination": "/onlyalpha-current-source", "Source": str(root), "RW": False},
            {
                "Type": "bind",
                "Destination": "/workspace/test-results",
                "Source": str(root / "test-results"),
                "RW": True,
            },
            *[
                {
                    "Type": "bind",
                    "Destination": f"/workspace/{dev_verification.WEB}/{name}",
                    "Source": str(root / ".test-cache/dev-tool-output" / name),
                    "RW": True,
                }
                for name in ("tsconfig.app.tsbuildinfo", "tsconfig.node.tsbuildinfo")
            ],
            *[
                {"Type": "image", "Destination": path, "Name": "sha256:" + "a" * 64, "RW": False}
                for path in dependencies
            ],
        ],
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "image",
                    "Source": "sha256:" + "a" * 64,
                    "Target": path,
                    "ImageOptions": {"Subpath": path.removeprefix("/")},
                }
                for path in dependencies
            ]
        },
    }


def test_ordinary_run_uses_exec_only_and_preserves_failure(monkeypatch, tmp_path: Path) -> None:
    calls = _host(monkeypatch, tmp_path, ["--web", "run", "--", "npx", "playwright", "test", "--workers=1"])
    assert dev_verification.main() == 0
    command, kwargs = calls[-1]
    assert "exec" in command and "-T" in command and "--interactive=false" in command
    assert command[-7:] == ["--web", "inside", "--", "npx", "playwright", "test", "--workers=1"]
    assert kwargs["env"]["ONLYALPHA_COMPOSE_NAMESPACE"] == "onlyalpha-dev"
    assert not any(word in command for word in ("build", "up", "down", "rm", "prune"))
    original_run = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: (
            (original_run(*a, **k), SimpleNamespace(returncode=7))[1]
            if "--operation-id" in a[0]
            else original_run(*a, **k)
        ),
    )
    assert dev_verification.main() == 7


@pytest.mark.parametrize(
    "present,rebuild,build_expected", [(True, False, False), (False, False, True), (True, True, True)]
)
def test_prepare_builds_only_missing_or_explicitly_rebuilt_fixed_image(
    monkeypatch, tmp_path: Path, present, rebuild, build_expected
):
    arguments = ["--rebuild", "prepare"] if rebuild else ["prepare"]
    calls = _host(monkeypatch, tmp_path, arguments, present=present)
    assert dev_verification.main() == 0
    assert any("build" in command for command, _ in calls) is build_expected
    up = calls[-1][0]
    assert up[-3:] == ["postgres", "clickhouse", "validation"]
    assert "--no-build" in up and "--pull" in up and "never" in up
    assert not any("down" in command for command, _ in calls)


def test_non_dev_namespace_is_refused_before_docker(monkeypatch, tmp_path: Path) -> None:
    calls = _host(monkeypatch, tmp_path, ["prepare"])
    monkeypatch.setenv("ONLYALPHA_COMPOSE_NAMESPACE", "onlyalpha-test-other")
    with pytest.raises(ValueError, match="PROJECT_REFUSED"):
        dev_verification.main()
    assert not calls


def test_foreign_worktree_is_refused_without_rebinding(monkeypatch, tmp_path: Path) -> None:
    calls = _host(monkeypatch, tmp_path, ["prepare"])
    record = _container(tmp_path / "other")
    monkeypatch.setattr(
        subprocess, "check_output", lambda command, **k: "container" if "ps" in command else json.dumps([record])
    )
    with pytest.raises(ValueError, match="WORKTREE_OR_DEPENDENCIES_REFUSED"):
        dev_verification.main()
    assert not calls


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-source",
        "host-dependency",
        "writable-dependency",
        "extra-business-volume",
        "missing-mount",
        "wrong-subpath",
        "business-dsn",
        "duplicate-dsn",
    ],
)
def test_container_admission_refuses_incomplete_or_wrong_context(tmp_path: Path, mutation: str) -> None:
    record = _container(tmp_path)
    if mutation == "wrong-source":
        record["Mounts"][0]["Source"] = str(tmp_path / "other")
    elif mutation == "host-dependency":
        record["Mounts"][-1]["Type"] = "bind"
    elif mutation == "writable-dependency":
        record["Mounts"][-1]["RW"] = True
    elif mutation == "extra-business-volume":
        record["Mounts"].append({"Type": "volume", "Destination": "/var/lib/onlyalpha"})
    elif mutation == "missing-mount":
        record["Mounts"].pop()
    elif mutation == "wrong-subpath":
        record["HostConfig"]["Mounts"][0]["ImageOptions"]["Subpath"] = "other"
    elif mutation == "business-dsn":
        record["Config"]["Env"] = ["ONLYALPHA_POSTGRES_DSN=postgresql://onlyalpha:onlyalpha@postgres/onlyalpha"]
    elif mutation == "duplicate-dsn":
        record["Config"]["Env"].append("ONLYALPHA_POSTGRES_DSN=postgresql://onlyalpha:onlyalpha@postgres/other_test")
    with pytest.raises(ValueError, match="DEV_VERIFICATION_.*REFUSED"):
        dev_verification.validate_container(record, tmp_path)


@pytest.mark.parametrize("platform,allowed", [("darwin", True), ("linux", False)])
def test_docker_desktop_bind_translation_requires_exact_platform_context(
    monkeypatch, tmp_path: Path, platform: str, allowed: bool
) -> None:
    record = _container(tmp_path)
    monkeypatch.setattr(sys, "platform", platform)
    for mount in record["Mounts"]:
        if mount["Type"] == "bind":
            mount["Source"] = "/host_mnt" + mount["Source"]
    if allowed:
        dev_verification.validate_container(record, tmp_path)
        record["Mounts"][0]["Source"] += "/other"
    with pytest.raises(ValueError, match="WORKTREE_OR_DEPENDENCIES_REFUSED"):
        dev_verification.validate_container(record, tmp_path)


def test_prepare_cannot_replace_container_with_retained_verification_work(monkeypatch, tmp_path: Path) -> None:
    calls = _host(monkeypatch, tmp_path, ["--rebuild", "prepare"])
    record = _container(tmp_path)
    monkeypatch.setattr(
        subprocess, "check_output", lambda command, **k: "container" if "ps" in command else json.dumps([record])
    )

    def busy(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", busy)
    with pytest.raises(ValueError, match="PREPARATION_NOT_ADMITTED"):
        dev_verification.main()
    assert len(calls) == 1 and calls[0][0][:3] == ["docker", "exec", "container"]


def _inside(monkeypatch, tmp_path: Path) -> None:
    _environment(tmp_path)
    admission = tmp_path / ".environment.json"
    admission.write_text(json.dumps(dev_verification.environment_inputs(tmp_path)))
    monkeypatch.setattr(dev_verification, "ROOT", tmp_path)
    monkeypatch.setattr(dev_verification, "ENVIRONMENT_RECORD", admission)
    monkeypatch.setattr(dev_verification, "CONTAINER_LOCK", tmp_path.parent / (tmp_path.name + ".lock"))
    monkeypatch.setenv("ONLYALPHA_DEV_SOURCE_ROOT", str(tmp_path))
    (tmp_path / dev_verification.CUT_METADATA).write_text(
        json.dumps(
            {
                "operation_id": "",
                "source_root": str(tmp_path),
                "inputs": dev_verification.source_inputs(tmp_path),
            }
        )
    )


def test_incompatible_environment_is_refused_before_starting_child(monkeypatch, tmp_path: Path) -> None:
    _inside(monkeypatch, tmp_path)
    (tmp_path / "uv.lock").write_text("new dependency")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("child must not start"))
    with pytest.raises(ValueError, match="ENVIRONMENT_REBUILD_REQUIRED"):
        dev_verification.run_inside(["true"])


def test_busy_container_is_refused_without_waiting(monkeypatch, tmp_path: Path) -> None:
    _inside(monkeypatch, tmp_path)
    with dev_verification.CONTAINER_LOCK.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="VERIFICATION_BUSY"):
            dev_verification.run_inside(["true"])


@pytest.mark.parametrize("status,expected", [(0, 0), (7, 7), (-15, 143)])
def test_child_inherits_lock_and_original_status_is_preserved(monkeypatch, tmp_path: Path, status, expected):
    _inside(monkeypatch, tmp_path)

    def start(command, **kwargs):
        assert command[-2:] == ["python", "test_command.py"]
        assert kwargs["cwd"] == tmp_path
        assert kwargs["start_new_session"] is True
        assert len(kwargs["pass_fds"]) == 1
        assert os.get_inheritable(kwargs["pass_fds"][0])
        return SimpleNamespace(pid=123, wait=lambda: status)

    monkeypatch.setattr(subprocess, "Popen", start)
    assert dev_verification.run_inside(["python", "test_command.py"]) == expected
    outcome = json.loads((tmp_path / "test-results/dev-verification/last-outcome.json").read_text())
    assert outcome["command_exit"] == status
    assert outcome["source_changed_during_verification"] is False


def test_changed_source_invalidates_successful_child_result(monkeypatch, tmp_path: Path) -> None:
    _inside(monkeypatch, tmp_path)

    def complete():
        (tmp_path / "source.py").write_text("changed during verification")
        return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=123, wait=complete))
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        dev_verification.run_inside(["true"])


def test_ordinary_command_failure_cannot_settle_unknown_browser_reset(monkeypatch, tmp_path: Path) -> None:
    _inside(monkeypatch, tmp_path)

    def failed_browser():
        fence = tmp_path / dev_verification.BROWSER_RESET_FENCE
        fence.parent.mkdir(parents=True, exist_ok=True)
        fence.write_text(json.dumps({"operation_id": "", "outcome": "UNKNOWN"}))
        return 1

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=123, wait=failed_browser))
    assert dev_verification.run_inside(["npx", "playwright", "test"]) == 1
    outcome = json.loads((tmp_path / "test-results/dev-verification/last-outcome.json").read_text())
    assert outcome["completed"] is False and outcome["browser_reset_unknown"] is True
    with pytest.raises(ValueError, match="BROWSER_RESET_UNKNOWN"):
        dev_verification.run_inside(["true"])


def test_unknown_browser_reset_keeps_machine_wide_fence_against_prepare_from_other_worktree(
    monkeypatch, tmp_path: Path
) -> None:
    calls = _host(monkeypatch, tmp_path, ["run", "--", "npx", "playwright", "test"])
    original_run = subprocess.run

    def unknown(command, **kwargs):
        result = original_run(command, **kwargs)
        if "--operation-id" in command:
            outcome = tmp_path / "test-results/dev-verification/last-outcome.json"
            receipt = json.loads(outcome.read_text())
            receipt["completed"] = False
            receipt["browser_reset_unknown"] = True
            outcome.write_text(json.dumps(receipt))
            return SimpleNamespace(returncode=1)
        return result

    monkeypatch.setattr(subprocess, "run", unknown)
    with pytest.raises(ValueError, match="COMMAND_COMPLETION_UNPROVEN"):
        dev_verification.main()
    assert (dev_verification.HOST_STATE / "dev-verification.pending.json").exists()
    before = len(calls)
    monkeypatch.setattr(dev_verification, "ROOT", tmp_path / "other-worktree")
    monkeypatch.setattr(sys, "argv", ["dev_verification.py", "prepare"])
    with pytest.raises(ValueError, match="OUTSTANDING_LIFECYCLE_REQUIRES_OWNER_RECOVERY"):
        dev_verification.main()
    assert len(calls) == before


def test_validation_is_source_mounted_and_cannot_start_business_services() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "deploy/docker-compose.dev.yml").read_text())
    service = compose["services"]["validation"]
    assert service["profiles"] == ["test"]
    assert service["image"] == dev_verification.IMAGE
    assert set(service["depends_on"]) == {"postgres", "clickhouse"}
    assert service["networks"] == ["database"]
    assert "ports" not in service and "privileged" not in service
    assert service["environment"]["ONLYALPHA_POSTGRES_DSN"].endswith("/onlyalpha_dev_validation_test")
    assert service["volumes"][0]["source"] == "../.test-cache/dev-source-cut"
    assert service["volumes"][0]["read_only"] is True
    assert service["volumes"][1]["read_only"] is True
    dependencies = [mount for mount in service["volumes"] if mount["type"] == "image"]
    assert {mount["target"] for mount in dependencies} == {
        "/workspace/.venv",
        "/workspace/packages/frontend/node_modules",
        "/usr/local/rustup",
        "/usr/local/cargo",
    }
    assert all(
        mount["read_only"] and mount["source"] == "${ONLYALPHA_DEV_TOOL_IMAGE_ID:-onlyalpha-browser-test:dev}"
        for mount in dependencies
    )
    assert not any("user-data" in str(mount) for mount in service["volumes"])
    dockerfile = (root / "deploy/Dockerfile.dev").read_text()
    for cache in (".vite", ".vite-temp"):
        # A read-only image mount cannot create a missing nested tmpfs mountpoint.
        assert f"/workspace/packages/frontend/node_modules/{cache}" in dockerfile
        assert any(f"/node_modules/{cache}:" in mount for mount in service["tmpfs"])


def test_fixed_images_are_shared_per_build_target() -> None:
    root = Path(__file__).resolve().parents[2]
    services = yaml.safe_load((root / "deploy/docker-compose.dev.yml").read_text())["services"]
    targets = {}
    for service in services.values():
        if "build" in service:
            target = service["build"]["target"]
            assert service["image"].endswith(":dev")
            if target in targets:
                assert service["image"] == targets[target]
            targets[target] = service["image"]


@pytest.mark.parametrize(
    "provider", ["test-data/external_plugins/onlyalpha_test_plugin", "test-data/runtime_factor_provider"]
)
@pytest.mark.parametrize("change", ["entry-points", "dependencies"])
def test_installed_local_distribution_metadata_is_an_environment_input(
    tmp_path: Path, provider: str, change: str
) -> None:
    _environment(tmp_path)
    admitted = dev_verification.environment_inputs(tmp_path)
    (tmp_path / provider / "pyproject.toml").write_text(change)
    assert dev_verification.environment_inputs(tmp_path) != admitted


@pytest.mark.parametrize("name", [".prettierrc.json", ".prettierignore"])
def test_hidden_execution_configuration_is_not_omitted(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("before")
    before = dev_verification.source_inputs(tmp_path)
    (tmp_path / name).write_text("changed")
    assert name in before and dev_verification.source_inputs(tmp_path) != before


def test_live_source_change_execute_restore_cannot_change_the_frozen_input(tmp_path: Path) -> None:
    _environment(tmp_path)
    source = tmp_path / "example.py"
    source.write_text("print('original')")
    inputs = dev_verification.freeze_source(tmp_path, "operation")
    source.write_text("print('intervening-change')")
    result = subprocess.run(
        [sys.executable, str(tmp_path / ".test-cache/dev-source-cut/example.py")],
        capture_output=True,
        text=True,
        check=True,
    )
    source.write_text("print('original')")
    assert result.stdout.strip() == "original"
    assert dev_verification.source_inputs(tmp_path) == inputs
    assert dev_verification.source_inputs(tmp_path / ".test-cache/dev-source-cut") == inputs


def test_frozen_git_preserves_real_head_and_tracked_files_without_private_config(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    hashes = dev_verification.capture_git(root, tmp_path, {})
    for arguments in (["rev-parse", "HEAD"], ["ls-files", "*pyproject.toml"]):
        expected = subprocess.check_output(["git", "-C", str(root), *arguments])
        observed = subprocess.check_output(["git", "-C", str(tmp_path), *arguments])
        assert observed == expected
    assert hashes == dev_verification.git_input_hashes(tmp_path)
    assert not (tmp_path / ".git/hooks").exists()
    assert "remote" not in (tmp_path / ".git/config").read_text()
    assert "credential" not in (tmp_path / ".git/config").read_text()
    (tmp_path / ".git/HEAD").write_text("different provenance")
    with pytest.raises(ValueError, match="GIT_CUT_MODIFIED"):
        dev_verification.capture_git(root, tmp_path, {"git_inputs": hashes})


def test_frozen_git_carries_exact_local_release_base_without_following_later_changes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    expected = subprocess.check_output(["git", "-C", str(root), "rev-parse", "origin/master"])
    hashes = dev_verification.capture_git(root, tmp_path, {})
    assert subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "origin/master"]) == expected
    assert subprocess.check_output(["git", "-C", str(tmp_path), "show", "origin/master:pyproject.toml"])
    assert "refs/remotes/origin/master" in hashes


def test_frozen_git_carries_exact_historical_authorization_bytes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    hashes = dev_verification.capture_git(root, tmp_path, {})
    relative = "contracts/product-api/v2/openapi.json"
    for revision in dev_verification.HISTORICAL_CONTRACT_TEST_REVISIONS:
        expected = subprocess.check_output(["git", "-C", str(root), "show", f"{revision}:{relative}"])
        observed = subprocess.check_output(["git", "-C", str(tmp_path), "show", f"{revision}:{relative}"])
        assert observed == expected
    assert hashes == dev_verification.git_input_hashes(tmp_path)


def test_research_source_cut_carries_current_provenance_and_cleans_it_on_next_run(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    project = tmp_path / "pyproject.toml"
    project.write_text('version = "0.1.0"\n')
    subprocess.run(["git", "-C", str(tmp_path), "add", "pyproject.toml"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "Source",
        ],
        check=True,
        capture_output=True,
    )
    project.write_text('version = "0.1.1"\n')
    raw = dev_verification.source_inputs(tmp_path)
    assert dev_verification.freeze_source(tmp_path, "research", research=True) == raw
    cut = tmp_path / ".test-cache/dev-source-cut"
    payload = json.loads(resolve_build_provenance_bytes(cut))
    assert payload["distribution_version"] == "0.1.1"
    assert (
        payload["source_revision"]
        == subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    )
    metadata = json.loads((cut / dev_verification.CUT_METADATA).read_text())
    assert metadata["inputs"] == dev_verification.source_inputs(cut)
    assert dev_verification.source_inputs(tmp_path) == raw
    monkeypatch.setattr(embed_build_provenance, "__file__", str(cut / "scripts/embed_build_provenance.py"))
    monkeypatch.setattr(sys, "argv", ["embed_build_provenance.py", "--check"])
    monkeypatch.setattr(
        embed_build_provenance, "write_build_provenance", lambda *args: pytest.fail("check must never write source")
    )
    assert embed_build_provenance.main() == 0
    assert dev_verification.source_inputs(cut) == metadata["inputs"]
    dev_verification.freeze_source(tmp_path, "ordinary")
    assert not (cut / "src/onlyalpha/_build_provenance.json").exists()
    assert dev_verification.source_inputs(cut) == raw
    with pytest.raises(ValueError, match="BUILD_PROVENANCE_INVALID"):
        embed_build_provenance.main()


@pytest.mark.parametrize(
    "mutation",
    ["missing-base-id", "different-base-id", "different-dependency-id", "mutable-dependency-tag", "writable-source"],
)
def test_complete_different_and_missing_identity_cannot_admit_dependency_mounts(tmp_path: Path, mutation: str) -> None:
    record = _container(tmp_path)
    if mutation == "missing-base-id":
        del record["Image"]
    elif mutation == "different-base-id":
        record["Image"] = "sha256:" + "b" * 64
    elif mutation == "different-dependency-id":
        record["Mounts"][-1]["Name"] = "sha256:" + "b" * 64
    elif mutation == "mutable-dependency-tag":
        record["Mounts"][-1]["Name"] = dev_verification.IMAGE
    elif mutation == "writable-source":
        record["Mounts"][0]["RW"] = True
    with pytest.raises(ValueError, match="DEV_VERIFICATION_.*(?:REFUSED|REQUIRED)"):
        dev_verification.validate_container(record, tmp_path)


@pytest.mark.parametrize("phase", ["build", "up", "exec"])
def test_killed_launcher_fences_pending_work_from_another_worktree(tmp_path: Path, phase: str) -> None:
    state = tmp_path / "host-state"
    child_code = "import os,sys,json; print(json.dumps({'pid':os.getpid()}),flush=True); sys.stdin.buffer.read(1); print('DONE',flush=True)"
    code = (
        "import subprocess,sys; from pathlib import Path; from scripts import dev_verification as d; "
        f"d.HOST_STATE=Path({str(state)!r}); "
        f"context=d.host_operation(Path({str(tmp_path / 'first')!r}),{'run' if phase == 'exec' else 'prepare'!r}); "
        "context.__enter__(); "
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}]); child.wait()"
    )
    launcher = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    child_pid = None
    try:
        assert launcher.stdout is not None and launcher.stdin is not None
        ready = json.loads(launcher.stdout.readline())
        child_pid = ready["pid"]
        launcher.kill()
        assert launcher.wait(timeout=10) == -signal.SIGKILL
        original = dev_verification.HOST_STATE
        dev_verification.HOST_STATE = state
        try:
            with pytest.raises(ValueError, match="OUTSTANDING_LIFECYCLE_REQUIRES_OWNER_RECOVERY"):
                with dev_verification.host_operation(tmp_path / "second", "prepare"):
                    pytest.fail("foreign worktree must not enter while outstanding work is unproved")
        finally:
            dev_verification.HOST_STATE = original
        launcher.stdin.write("x")
        launcher.stdin.flush()
        assert launcher.stdout.readline().strip() == "DONE"
        child_pid = None
    finally:
        if launcher.poll() is None:
            launcher.kill()
            launcher.wait(timeout=10)
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_actual_command_retains_lock_after_intermediate_wrapper_is_killed(monkeypatch, tmp_path: Path) -> None:
    lock_path = tmp_path / "command.lock"
    held = lock_path.open("a")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    descriptor = held.fileno()
    command = (
        "import os,sys,json; fd=int(os.environ['ONLYALPHA_DEV_VERIFICATION_LOCK_FD']); os.fstat(fd); "
        "print(json.dumps({'pid':os.getpid()}),flush=True); sys.stdin.buffer.read(1); os.close(fd); print('DONE',flush=True)"
    )
    wrapper_code = (
        "import sys; from types import SimpleNamespace; from scripts import compose_test as c; "
        "fake=type('Connection',(),{'__enter__':lambda s:s,'__exit__':lambda *a:None,"
        "'execute':lambda *a:SimpleNamespace(fetchone=lambda:(1,))}); "
        "c.psycopg.connect=lambda *a,**k:fake(); "
        f"sys.argv=['compose_test.py',sys.executable,'-c',{command!r}]; sys.exit(c.main())"
    )
    environment = {
        **os.environ,
        "ONLYALPHA_POSTGRES_DSN": "postgresql://localhost/onlyalpha_lock_test",
        "ONLYALPHA_DEV_VERIFICATION_LOCK_FD": str(descriptor),
    }
    wrapper = subprocess.Popen(
        [sys.executable, "-c", wrapper_code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=environment,
        pass_fds=(descriptor,),
    )
    child_pid = None
    try:
        assert wrapper.stdout is not None and wrapper.stdin is not None
        child_pid = json.loads(wrapper.stdout.readline())["pid"]
        held.close()
        wrapper.kill()
        assert wrapper.wait(timeout=10) == -signal.SIGKILL
        monkeypatch.setattr(dev_verification, "CONTAINER_LOCK", lock_path)
        with pytest.raises(ValueError, match="VERIFICATION_BUSY"):
            dev_verification.run_inside(["true"])
        wrapper.stdin.write("x")
        wrapper.stdin.flush()
        assert wrapper.stdout.readline().strip() == "DONE"
        child_pid = None
        with lock_path.open("a") as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        held.close()
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait(timeout=10)
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGKILL, signal.SIGINT])
def test_signalled_actual_command_does_not_become_an_ordinary_wrapper_completion(tmp_path: Path, number: int) -> None:
    command = (
        "import os,sys,signal; signal.signal(signal.SIGINT,signal.SIG_DFL); "
        "print(os.getpid(),flush=True); sys.stdin.buffer.read(1)"
    )
    wrapper_code = (
        "import sys; from types import SimpleNamespace; from scripts import compose_test as c; "
        "fake=type('Connection',(),{'__enter__':lambda s:s,'__exit__':lambda *a:None,"
        "'execute':lambda *a:SimpleNamespace(fetchone=lambda:(1,))}); "
        "c.psycopg.connect=lambda *a,**k:fake(); "
        f"sys.argv=['compose_test.py',sys.executable,'-c',{command!r}]; sys.exit(c.main())"
    )
    with (tmp_path / "command.lock").open("a") as held:
        descriptor = held.fileno()
        environment = {
            **os.environ,
            "ONLYALPHA_POSTGRES_DSN": "postgresql://localhost/onlyalpha_lock_test",
            "ONLYALPHA_DEV_VERIFICATION_LOCK_FD": str(descriptor),
        }
        wrapper = subprocess.Popen(
            [sys.executable, "-c", wrapper_code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=environment,
            pass_fds=(descriptor,),
        )
        child_pid = None
        try:
            assert wrapper.stdout is not None
            child_pid = int(wrapper.stdout.readline())
            os.kill(child_pid, number)
            assert wrapper.wait(timeout=10) == -number
            child_pid = None
        finally:
            if wrapper.poll() is None:
                wrapper.kill()
                wrapper.wait(timeout=10)
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def test_docker_desktop_may_report_file_binds_without_directory_prefix(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    record = _container(tmp_path)
    for mount in record["Mounts"]:
        if mount["Type"] == "bind" and not mount["Destination"].endswith(".tsbuildinfo"):
            mount["Source"] = "/host_mnt" + mount["Source"]
    dev_verification.validate_container(record, tmp_path)


@pytest.mark.parametrize("mutation", ["wrong-file", "writable-file", "wrong-directory", "linux"])
def test_desktop_file_bind_representation_preserves_exact_identity(monkeypatch, tmp_path: Path, mutation: str) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    record = _container(tmp_path)
    for mount in record["Mounts"]:
        if mount["Type"] == "bind" and not mount["Destination"].endswith(".tsbuildinfo"):
            mount["Source"] = "/host_mnt" + mount["Source"]
    file_mount = next(m for m in record["Mounts"] if m["Destination"].endswith(".tsbuildinfo"))
    if mutation == "wrong-file":
        file_mount["Source"] += ".other"
    elif mutation == "writable-file":
        file_mount["RW"] = False
    elif mutation == "wrong-directory":
        record["Mounts"][0]["Source"] += "/other"
    else:
        monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ValueError, match="WORKTREE_OR_DEPENDENCIES_REFUSED"):
        dev_verification.validate_container(record, tmp_path)


@pytest.mark.parametrize("product", [False, True])
def test_frozen_source_prunes_removed_package_directories(tmp_path: Path, product: bool) -> None:
    _environment(tmp_path)
    source = tmp_path / "plugs/retired/src/provider.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1")
    dev_verification.freeze_source(tmp_path, "before-removal", product=product)
    source.unlink()
    source.parent.rmdir()
    source.parent.parent.rmdir()
    dev_verification.freeze_source(tmp_path, "after-removal", product=product)
    cut = tmp_path / (".test-cache/dev-product-source" if product else ".test-cache/dev-source-cut")
    assert not (cut / "plugs/retired").exists()
    assert (cut / "plugs/example/pyproject.toml").is_file()


def test_frozen_source_preserves_an_empty_directory_still_present_in_source(tmp_path: Path) -> None:
    _environment(tmp_path)
    source = tmp_path / "plugs/retained/provider.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1")
    dev_verification.freeze_source(tmp_path, "before-removal", product=True)
    source.unlink()
    dev_verification.freeze_source(tmp_path, "after-removal", product=True)
    assert (tmp_path / ".test-cache/dev-product-source/plugs/retained").is_dir()


def test_rust_toolchain_and_dependencies_bind_environment_but_source_does_not(tmp_path: Path) -> None:
    _environment(tmp_path)
    rust = tmp_path / "rust-toolchain.toml"
    rust.write_text('[toolchain]\nchannel="1.99.1"\n')
    lock = tmp_path / "Cargo.lock"
    lock.write_text("version=4\n")
    manifest = tmp_path / "crates/onlyalpha-kernel/predicates/Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname="onlyalpha-predicates"\n')
    admitted = dev_verification.environment_inputs(tmp_path)
    source = manifest.parent / "src/lib.rs"
    source.parent.mkdir()
    source.write_text("pub fn predicate() {}")
    assert dev_verification.environment_inputs(tmp_path) == admitted
    for path in (rust, lock, manifest):
        before = path.read_text()
        path.write_text(before + "\n# changed input\n")
        assert dev_verification.environment_inputs(tmp_path) != admitted
        path.write_text(before)


def test_desktop_can_report_each_exact_bind_with_its_native_alias(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    record = _container(tmp_path)
    record["Mounts"][0]["Source"] = "/host_mnt" + record["Mounts"][0]["Source"]
    dev_verification.validate_container(record, tmp_path)


def test_rust_compiler_and_proxies_are_exact_readonly_image_dependencies(tmp_path: Path) -> None:
    record = _container(tmp_path)
    for destination in ("/usr/local/rustup", "/usr/local/cargo"):
        mounts = [m for m in record["Mounts"] if m["Destination"] == destination]
        assert len(mounts) == 1
        assert mounts[0]["Type"] == "image" and mounts[0]["RW"] is False
    dev_verification.validate_container(record, tmp_path)


def test_nested_market_data_manifests_are_environment_inputs(tmp_path: Path) -> None:
    _environment(tmp_path)
    manifest = tmp_path / "crates/onlyalpha-kernel/market_data/state/Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname="onlyalpha-market-data-state"\n')
    before = dev_verification.environment_inputs(tmp_path)
    assert str(manifest.relative_to(tmp_path)) in before
    manifest.write_text(manifest.read_text() + 'version="0.10.10"\n')
    assert dev_verification.environment_inputs(tmp_path) != before


def test_infrastructure_cargo_manifest_is_an_environment_input(tmp_path: Path) -> None:
    _environment(tmp_path)
    manifest = tmp_path / "crates/onlyalpha-calculation-bridge/Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname="onlyalpha-calculation-bridge"\n')
    admitted = dev_verification.environment_inputs(tmp_path)
    manifest.write_text(manifest.read_text() + "# dependency change\n")
    assert dev_verification.environment_inputs(tmp_path) != admitted


def test_native_plugin_manifests_are_environment_inputs(tmp_path: Path) -> None:
    _environment(tmp_path)
    manifest = tmp_path / "plugs/onlyalpha-plugin-binance/Cargo.toml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('[package]\nname="onlyalpha-plugin-binance"\n')
    before = dev_verification.environment_inputs(tmp_path)
    assert str(manifest.relative_to(tmp_path)) in before
    manifest.write_text(manifest.read_text() + "build=false\n")
    assert dev_verification.environment_inputs(tmp_path) != before
