"""Production import contracts admit current sources and reject real import edges."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.architecture


@pytest.mark.parametrize(
    "module,forbidden,contract",
    [
        ("onlyalpha/canonical.py", "onlyalpha_plugin_tushare", "Public SDK"),
        ("onlyalpha/canonical.py", "onlyalpha_backend_algorithms.worker_io", "Public SDK"),
        ("onlyalpha_backend_algorithms/worker_io.py", "onlyalpha_plugin_binance", "Restricted algorithm runner"),
        ("onlyalpha_backend_algorithms/worker_io.py", "onlyalpha_backend", "Restricted algorithm runner"),
    ],
)
def test_current_import_contract_rejects_real_forbidden_edges(
    tmp_path: Path, module: str, forbidden: str, contract: str
) -> None:
    # Clone actual maintained source packages; no replacement implementation runs.
    for package, source in [
        ("onlyalpha", "packages/backend/python/algorithms/sdk/onlyalpha"),
        ("onlyalpha_backend_algorithms", "packages/backend/python/algorithms/src/onlyalpha_backend_algorithms"),
    ]:
        shutil.copytree(ROOT / source, tmp_path / package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    config = tmp_path / "pyproject.toml"
    config.write_bytes((ROOT / "pyproject.toml").read_bytes())
    tool = shutil.which("lint-imports")
    assert tool is not None, "the existing import-linter dependency must be installed"
    command = [tool, "--config", str(config), "--no-cache"]
    environment = {**os.environ, "PYTHONPATH": str(tmp_path)}
    admitted = subprocess.run(
        command, cwd=tmp_path, env=environment, text=True, capture_output=True, check=False, timeout=30
    )
    assert admitted.returncode == 0, admitted.stdout + admitted.stderr
    target = tmp_path / module
    target.chmod(target.stat().st_mode | stat.S_IWUSR)
    target.write_text(target.read_text() + "\nimport " + forbidden + "\n")
    refused = subprocess.run(
        command, cwd=tmp_path, env=environment, text=True, capture_output=True, check=False, timeout=30
    )
    assert refused.returncode != 0
    assert contract in refused.stdout and "BROKEN" in refused.stdout, refused.stdout + refused.stderr
