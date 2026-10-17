from __future__ import annotations

from pathlib import Path

from scripts.rust_kernel_check import build_commands, compiler_environment


def test_rust_commands_cover_locked_offline_profiles_without_parallel_tests() -> None:
    commands = build_commands("aarch64-unknown-linux-gnu")
    assert any(command[:2] == ["cargo", "fmt"] for command in commands)
    assert any(command[:2] == ["cargo", "clippy"] and command[-2:] == ["-D", "warnings"] for command in commands)
    for action in ("test", "build"):
        selected = [command for command in commands if command[1] == action]
        assert len(selected) == 2
        assert sum("--release" in command for command in selected) == 1
        assert all("--frozen" in command and "--offline" in command and "-j1" in command for command in selected)
        if action == "test":
            assert all("--test-threads=1" in command for command in selected)


def test_compiler_environment_removes_ambient_flags_and_wrappers(tmp_path: Path) -> None:
    env = compiler_environment(
        {
            "PATH": "/tools",
            "RUSTUP_HOME": "/official",
            "RUSTFLAGS": "-C overflow-checks=no",
            "RUSTC_WRAPPER": "/untrusted",
            "CARGO_PROFILE_RELEASE_PANIC": "abort",
        },
        tmp_path,
    )
    assert env["PATH"] == "/tools" and env["RUSTUP_HOME"] == "/official"
    assert "RUSTFLAGS" not in env and "RUSTC_WRAPPER" not in env
    assert "CARGO_PROFILE_RELEASE_PANIC" not in env
    assert env["CARGO_NET_OFFLINE"] == "true"
    assert env["RUSTUP_AUTO_INSTALL"] == "0"
    assert env["CARGO_TARGET_DIR"] == str(tmp_path)


def test_rejected_host_cannot_leave_a_prior_build_receipt(monkeypatch, tmp_path: Path) -> None:
    import pytest

    import scripts.rust_kernel_check as check

    receipt = tmp_path / "test-results/rust-kernel/last-run.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"prior":"build"}')
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setattr(check.sys, "platform", "darwin")
    with pytest.raises(ValueError, match="LINUX_REQUIRED"):
        check.main()
    assert not receipt.exists()
