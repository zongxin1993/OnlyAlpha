from pathlib import Path

import pytest

from onlyalpha.cli import only_parse_args
from tests.runtime_runner import only_write_migrated_cluster_config


def test_external_plugin_dry_run_cannot_reintroduce_removed_root_product_cli(tmp_path: Path) -> None:
    config = only_write_migrated_cluster_config("tests/fixtures/legacy_macd/cluster_external_plugins.yaml", tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        only_parse_args(
            [
                "run",
                "--config",
                str(config),
                "--user-data",
                str(tmp_path),
                "--dry-run",
            ]
        )
    assert exc_info.value.code == 2
    assert not (tmp_path / "runs").exists()
