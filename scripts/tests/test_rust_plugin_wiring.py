"""Rust 插件清退后的发行接线，避免验证入口静默丢失。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml

from scripts import pre_commit_quality, test_suite
from scripts.release_metadata import plugin_release_members

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.architecture


def test_each_rust_plugin_is_tested_and_linted_before_distribution_build():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    members = plugin_release_members(ROOT)
    owners = [item for item in members if item[3]]
    assert owners
    assert not ({unit for unit, _, _, _ in owners} & {unit for unit, _, _, rust in members if not rust})
    required = set(jobs["required"]["needs"])
    build = set(jobs["build-smoke"]["needs"])
    for _, directory, package, _ in owners:
        assert not (ROOT / directory / "pyproject.toml").exists()
        assert not list((ROOT / directory).rglob("*.py"))
        assert not list((ROOT / directory).rglob("py.typed"))
        name = package["name"]
        selected = []
        for key, job in jobs.items():
            commands = [step.get("run", "") for step in job.get("steps", [])]
            if any(f"-p {name}" in cmd and "cargo test --locked" in cmd for cmd in commands):
                assert any(
                    f"-p {name}" in cmd and "cargo clippy --locked" in cmd and "--all-targets -- -D warnings" in cmd
                    for cmd in commands
                )
                assert any(f"-p {name}" in cmd and "cargo fmt" in cmd and "-- --check" in cmd for cmd in commands)
                assert key in required and key in build
                selected.append(key)
        assert len(selected) == 1, (directory, selected)
    static = test_suite.RELEASE_STATIC_COMMANDS
    arguments = next(args for args in static if "scripts/rust_kernel_check.py" in args and "--package" in args)
    packages = {arguments[i + 1] for i, value in enumerate(arguments) if value == "--package"}
    assert {p["name"] for _, _, p, _ in owners} <= packages


def test_python_quality_scopes_cover_maintained_execution_roots_and_real_paths():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    declared = set(config["tool"]["mypy"]["files"])
    assert {scope.source_path for scope in pre_commit_quality.MYPY_SCOPES} == declared
    for scope in pre_commit_quality.MYPY_SCOPES:
        assert (ROOT / scope.config_file).is_file()
        assert (ROOT / scope.source_path).is_dir()
        selected = pre_commit_quality.resolve_mypy_scopes([scope.source_path + "/changed.py"], check_all=False)
        assert scope in selected
    assert set(pre_commit_quality.resolve_mypy_scopes(["uv.lock"], check_all=False)) == set(
        pre_commit_quality.MYPY_SCOPES
    )
    assert config["tool"]["mypy"]["strict"] is True
    assert all((ROOT / path).is_dir() for path in config["tool"]["pytest"]["ini_options"]["testpaths"])
