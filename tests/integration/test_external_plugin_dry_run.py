from pathlib import Path

from onlyalpha.cli import main


def test_external_plugin_dry_run_reports_discovery_and_does_not_create_run(tmp_path: Path, capsys: object) -> None:
    exit_code = main(
        [
            "run",
            "--config",
            "tests/fixtures/legacy_macd/cluster_external_plugins.yaml",
            "--user-data",
            str(tmp_path),
            "--dry-run",
        ]
    )
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert exit_code == 0
    assert "test-external-data" in output
    assert "test-external-broker" in output
    assert "binding=data_source:external-test-data->test-external-data" in output
    assert not (tmp_path / "runs").exists()
