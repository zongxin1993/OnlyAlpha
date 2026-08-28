import subprocess
import sys
from pathlib import Path

from tests.runtime_runner import only_write_migrated_cluster_config


def test_external_plugin_backtest_cannot_bypass_product_control_plane_through_root_cli(tmp_path: Path) -> None:
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
    assert completed.returncode == 2
    assert "invalid choice: 'run'" in completed.stderr
    assert completed.stdout == ""
    assert not (tmp_path / "runs").exists()
