import json
import subprocess
import sys
from pathlib import Path


def test_external_plugin_backtest_runs_through_installed_cli(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "onlyalpha.cli",
            "run",
            "--config",
            "tests/fixtures/legacy_macd/cluster_external_plugins.yaml",
            "--user-data",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "COMPLETED"
    assert result["cluster_count"] == 1
    assert Path(result["manifest_path"]).is_file()
