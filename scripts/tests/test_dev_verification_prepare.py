from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import dev_verification as verification

pytestmark = pytest.mark.architecture


@pytest.mark.parametrize("collect_only", [False, True])
@pytest.mark.parametrize(
    "mode", ["backtest-publication", "research-publication", "backtest-owner:queued-cancel", "normal"]
)
def test_backtest_builds_before_scenario_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, collect_only: bool, mode: str
) -> None:
    from packages.backend.tests.application import backtest_native_host, test_strategy_research_evidence
    from packages.backend.tests.application import conftest as application
    from scripts import native_http_contract

    events = []

    def build(name):
        events.append(name)
        return tmp_path / name

    class TimeoutObserver:
        @pytest.hookimpl(tryfirst=True)
        def pytest_timeout_set_timer(self, item, settings):
            assert settings.timeout == 120 and not settings.func_only
            events.append("timeout")

    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setattr(application, "__file__", str(tmp_path / "conftest.py"))
    monkeypatch.setattr(
        test_strategy_research_evidence, "_build_strategy_evidence_owner_binary", lambda **_: build("probe")
    )
    monkeypatch.setattr(native_http_contract, "native_executable", lambda **_: build("backend"))
    monkeypatch.setattr(backtest_native_host, "build_web_assets", lambda _: build("web"))
    if mode == "backtest-publication":
        target = tmp_path / "test_backtest_worker_publication.py"
        target.write_text(
            "import pytest\n\n"
            "@pytest.mark.timeout(120)\n"
            "def test_scenario(request):\n"
            "    assert request.getfixturevalue('backtest_fault_probe').name == 'probe'\n"
            "    assert request.getfixturevalue('backtest_web_assets').name == 'web'\n"
        )
        expected = ["probe", "backend", "web", "timeout"]
    elif mode == "research-publication":
        target = tmp_path / "test_research_worker_publication.py"
        target.write_text(
            "import pytest\n\n"
            "@pytest.mark.timeout(120)\n"
            "def test_scenario(backtest_fault_probe):\n"
            "    assert backtest_fault_probe.name == 'probe'\n"
        )
        expected = ["probe", "timeout"]
    else:
        target = tmp_path / "test_strategy_research_evidence.py"
        target.write_text(
            "import pytest\n\n"
            "@pytest.mark.timeout(120)\n"
            f"@pytest.mark.parametrize('mode', [{mode!r}])\n"
            "def test_scenario(mode, request):\n"
            "    if mode.startswith('backtest-owner:'):\n"
            "        assert request.getfixturevalue('backtest_fault_probe').name == 'probe'\n"
            "        assert request.getfixturevalue('backtest_web_assets').name == 'web'\n"
        )
        expected = ["probe", "backend", "web", "timeout"] if mode.startswith("backtest-owner:") else ["timeout"]
    # 内层计时器不能覆盖外层 pytest 的 SIGALRM。
    command = [
        "--noconftest",
        "--rootdir",
        str(tmp_path.parent),
        "--import-mode=importlib",
        "-p",
        "pytest_timeout",
        "--timeout-method=thread",
        "-p",
        "no:cacheprovider",
        "-q",
        str(target),
    ]
    if collect_only:
        command.append("--collect-only")
    assert pytest.main(command, plugins=[application, TimeoutObserver()]) == pytest.ExitCode.OK
    assert events == ([] if collect_only else expected)


@pytest.fixture
def docker_calls(monkeypatch, tmp_path):
    calls = []
    state = {"running": False, "available": False, "busy": False, "pull_failure": False, "envs": []}
    monkeypatch.setattr(verification, "ROOT", tmp_path)
    monkeypatch.setattr(verification, "freeze_source", lambda *args, **kwargs: {})
    monkeypatch.setattr(verification, "source_inputs", lambda *args: {})
    monkeypatch.setattr(verification, "validate_container", lambda *args: None)
    monkeypatch.delenv("ONLYALPHA_COMPOSE_NAMESPACE", raising=False)

    def output(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "ps", "-aq"]:
            return "container\n" if state["running"] else ""
        if command[:2] == ["docker", "inspect"]:
            return json.dumps([{"Id": "container", "Image": "tool-image", "Mounts": [], "State": {"Running": True}}])
        assert command == ["docker", "image", "inspect", verification.IMAGE]
        return json.dumps([{"Id": "tool-image"}])

    def run(command, **kwargs):
        calls.append(command)
        if "env" in kwargs:
            state["envs"].append(kwargs["env"])
        if command[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(returncode=0 if state["available"] else 1)
        if command[:2] == ["docker", "exec"]:
            return SimpleNamespace(returncode=1 if state["busy"] else 0)
        if "pull" in command and state["pull_failure"]:
            raise subprocess.CalledProcessError(1, command)
        if "exec" in command:
            path = tmp_path / "test-results/dev-verification/last-outcome.json"
            path.write_text(json.dumps({"operation_id": "operation", "completed": True}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(verification.subprocess, "check_output", output)
    monkeypatch.setattr(verification.subprocess, "run", run)
    return calls, state


def invoke(mode, reservation):
    return verification.run_host(
        mode, ["python", "-V"] if mode == "run" else [], web=False, rebuild=False, reservation=reservation
    )


@pytest.mark.parametrize("available", [False, True])
def test_prepare_pulls_only_pinned_databases_before_build_or_up(docker_calls, available):
    calls, state = docker_calls
    state["available"] = available
    reservation = {"operation_id": "operation"}
    assert invoke("prepare", reservation) == 0
    pull = next(index for index, call in enumerate(calls) if "pull" in call)
    assert calls[pull][-5:] == ["pull", "--policy", "missing", "postgres", "clickhouse"]
    assert all(pull < index for index, call in enumerate(calls) if "build" in call or "up" in call)
    assert next(call for call in calls if "up" in call)[-7:] == [
        "--no-build",
        "--pull",
        "never",
        "--wait",
        "postgres",
        "clickhouse",
        "validation",
    ]
    assert reservation["completed"] is True


def test_prepare_creates_missing_host_bind_source(docker_calls, monkeypatch, tmp_path):
    _, state = docker_calls
    monkeypatch.setattr(verification, "_dev_container_identity", lambda: (1001, 127))
    assert not (tmp_path / "test-results").exists()
    previous = os.umask(0o002)
    try:
        assert invoke("prepare", {"operation_id": "operation"}) == 0
    finally:
        os.umask(previous)
    assert stat.S_IMODE((tmp_path / "test-results").stat().st_mode) & 0o1022 == 0
    assert stat.S_IMODE((tmp_path / "test-results/dev-verification").stat().st_mode) & 0o1022 == 0
    assert state["envs"]
    assert all(env["ONLYALPHA_DEV_UID"] == "1001" and env["ONLYALPHA_DEV_GID"] == "127" for env in state["envs"])


def test_prepare_strips_group_world_write_and_sticky_bits_non_recursively(docker_calls, tmp_path):
    results = tmp_path / "test-results"
    metrics = results / "metrics"
    metrics.mkdir(parents=True)
    results.chmod(0o1777)
    metrics.chmod(0o1777)
    shard = metrics / "shard-1.json"
    shard.write_text("{}")
    shard.chmod(0o644)
    assert invoke("prepare", {"operation_id": "operation"}) == 0
    assert stat.S_IMODE(results.stat().st_mode) == 0o755
    assert stat.S_IMODE(metrics.stat().st_mode) == 0o755
    assert stat.S_IMODE(shard.stat().st_mode) == 0o644


def test_prepare_refuses_symlinked_test_results(docker_calls, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "test-results").symlink_to(outside)
    with pytest.raises(ValueError, match="DEV_VERIFICATION_BIND_PATH_SYMLINK_REFUSED"):
        invoke("prepare", {"operation_id": "operation"})


def test_ensure_protected_bind_file_strips_write_bits_and_refuses_symlink(tmp_path):
    target = tmp_path / "tsconfig.app.tsbuildinfo"
    previous = os.umask(0o002)
    try:
        verification._ensure_protected_bind_file(target)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(target.stat().st_mode) & 0o022 == 0
    target.chmod(0o666)
    verification._ensure_protected_bind_file(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    link = tmp_path / "tsconfig.node.tsbuildinfo"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="DEV_VERIFICATION_BIND_PATH_SYMLINK_REFUSED"):
        verification._ensure_protected_bind_file(link)


@pytest.mark.parametrize(
    ("platform", "uid", "gid", "expected"),
    [
        ("linux", 1001, 127, (1001, 127)),
        ("linux", 1000, 1000, (1000, 1000)),
        ("linux", 0, 0, (10001, 10001)),
        ("linux", 65534, 65534, (10001, 10001)),
        ("darwin", 501, 20, (10001, 10001)),
    ],
)
def test_dev_container_identity_matches_non_root_linux_host(monkeypatch, platform, uid, gid, expected):
    monkeypatch.setattr(verification.sys, "platform", platform)
    monkeypatch.setattr(verification.os, "geteuid", lambda: uid)
    monkeypatch.setattr(verification.os, "getegid", lambda: gid)
    assert verification._dev_container_identity() == expected


def test_freeze_source_enforces_protected_modes_under_permissive_umask(tmp_path):
    (tmp_path / "packages/frontend").mkdir(parents=True)
    (tmp_path / "packages/frontend/index.ts").write_text("export const x = 1;\n")
    previous = os.umask(0o002)
    try:
        verification.freeze_source(tmp_path, "operation", product=True)
    finally:
        os.umask(previous)
    cut = tmp_path / ".test-cache/dev-product-source"
    assert stat.S_IMODE(cut.stat().st_mode) & 0o1022 == 0
    assert stat.S_IMODE((cut / "packages").stat().st_mode) & 0o022 == 0
    assert stat.S_IMODE((tmp_path / ".test-cache/dev-tool-output/tsconfig.app.tsbuildinfo").stat().st_mode) & 0o022 == 0


def test_run_never_pulls_or_builds_images(docker_calls):
    calls, state = docker_calls
    state["running"] = True
    reservation = {"operation_id": "operation"}
    assert invoke("run", reservation) == 0
    assert not any("pull" in call or "build" in call or "up" in call for call in calls)
    assert reservation["completed"] is True


def test_failed_pull_preserves_unfinished_reservation_without_build_or_up(docker_calls):
    calls, state = docker_calls
    state["pull_failure"] = True
    reservation = {"operation_id": "operation"}
    with pytest.raises(subprocess.CalledProcessError):
        invoke("prepare", reservation)
    assert reservation["completed"] is False
    assert not any("build" in call or "up" in call for call in calls)


@pytest.mark.parametrize("reason", ["busy", "wrong-project"])
def test_refused_owner_never_pulls_images(docker_calls, monkeypatch, reason):
    calls, state = docker_calls
    if reason == "busy":
        state.update(running=True, busy=True)
    else:
        monkeypatch.setenv("ONLYALPHA_COMPOSE_NAMESPACE", "another-project")
    with pytest.raises(ValueError):
        invoke("prepare", {"operation_id": "operation"})
    assert not any("pull" in call for call in calls)


def test_openapi_run_passes_exact_command_baseline_to_freeze(docker_calls, monkeypatch):
    _, state = docker_calls
    state["running"] = True
    captures = []
    monkeypatch.setattr(verification, "freeze_source", lambda *args, **kwargs: captures.append((args, kwargs)) or {})
    baseline = "a" * 40
    command = ["python", "scripts/openapi_contract.py", "verify", "--base", baseline]
    assert (
        verification.run_host("run", command, web=False, rebuild=False, reservation={"operation_id": "operation"}) == 0
    )
    assert captures[0][1]["required_git_revisions"] == (baseline,)
