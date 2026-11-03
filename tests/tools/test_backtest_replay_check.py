"""The canonical replay lane owns real installed arithmetic without legacy backend inputs."""

from __future__ import annotations

import builtins
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import backtest_replay_check
from scripts.build_algorithm_sdk import ROOT


def test_replay_environment_uses_installed_algorithms_without_legacy_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = builtins.__import__
    forbidden = (
        "onlyalpha_calculation_worker",
        "onlyalpha.core",
        "onlyalpha.domain",
        "onlyalpha.market",
        "onlyalpha.research",
    )

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        assert not any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    environment = backtest_replay_check.replay_environment(ROOT, tmp_path)
    assert set(environment) == {
        "ONLYALPHA_TRADING_TEST_INPUT",
        "ONLYALPHA_TRADING_TEST_INSTALLATION",
        "ONLYALPHA_TRADING_TEST_ARTIFACT",
    }
    installation = Path(environment["ONLYALPHA_TRADING_TEST_INSTALLATION"])
    assert installation.is_relative_to(tmp_path)
    assert Path(environment["ONLYALPHA_TRADING_TEST_INPUT"]).is_file()
    result = subprocess.run(
        [
            str(installation / "bin/python"),
            "-B",
            "-I",
            "-c",
            "import importlib.util;import onlyalpha_backend_algorithms.trading_session;"
            "assert importlib.util.find_spec('onlyalpha.domain') is None;"
            "assert importlib.util.find_spec('onlyalpha_calculation_worker') is None",
        ],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
