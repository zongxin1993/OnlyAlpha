import json
import subprocess
import sys
from pathlib import Path

from tests.runtime_runner import only_write_migrated_cluster_config


def test_external_plugin_backtest_runs_through_installed_cli(tmp_path: Path) -> None:
    config = only_write_migrated_cluster_config("tests/fixtures/legacy_macd/cluster_external_plugins.yaml", tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "onlyalpha.cli",
            "run",
            "--config",
            str(config),
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
