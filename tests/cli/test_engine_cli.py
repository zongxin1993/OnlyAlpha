from pathlib import Path

import pytest

from onlyalpha.application.engine_runner import OnlyEngineApplicationRunner
from onlyalpha.cli import main, only_parse_args, only_resolve_config_paths, only_resolve_user_data_root

CONFIG = "tests/fixtures/legacy_macd/cluster.json"
FAST_CONFIG = "tests/fixtures/legacy_macd/cluster_fast.json"


def test_repeated_config_order_is_preserved_and_deduplicated() -> None:
    args = only_parse_args(["run", "--config", FAST_CONFIG, "--config", CONFIG, "--config", FAST_CONFIG])
    paths = only_resolve_config_paths(args)
    assert [item.name for item in paths] == ["cluster_fast.json", "cluster.json"]
    assert paths[0].name == "cluster_fast.json"
    assert paths[1].name == "cluster.json"


def test_user_data_precedence(tmp_path: Path, monkeypatch: object) -> None:
    env_root = tmp_path / "environment"
    cli_root = tmp_path / "cli"
    monkeypatch.setenv("ONLYALPHA_USER_DATA", str(env_root))  # type: ignore[attr-defined]
    assert only_resolve_user_data_root(None) == env_root.resolve()
    assert only_resolve_user_data_root(str(cli_root)) == cli_root.resolve()


def test_dry_run_does_not_create_run_output(tmp_path: Path) -> None:
    assert main(["run", "--config", CONFIG, "--user-data", str(tmp_path), "--dry-run"]) == 0
    assert not (tmp_path / "runs").exists()


def test_snapshot_runtime_failure_is_reported_without_a_traceback(
    tmp_path: Path, monkeypatch: object, capsys: object
) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        OnlyEngineApplicationRunner,
        "snapshot",
        lambda self, engine: (_ for _ in ()).throw(RuntimeError("warmup failed closed")),
    )
    assert main(["snapshot", "--config", CONFIG, "--user-data", str(tmp_path)]) == 2
    assert "onlyalpha: warmup failed closed" in capsys.readouterr().out  # type: ignore[attr-defined]


def test_scenario_validate_run_and_retired_profile_query_cli(tmp_path: Path, capsys: object) -> None:
    scenario = "tests/fixtures/scenarios/generic_t0_cash.yaml"
    assert main(["scenario", "validate", scenario, "--format", "json"]) == 0
    assert '"valid": true' in capsys.readouterr().out  # type: ignore[attr-defined]

    assert main(["scenario", "run", scenario, "--user-data", str(tmp_path), "--format", "json"]) == 0
    assert '"status": "PASSED"' in capsys.readouterr().out  # type: ignore[attr-defined]

    with pytest.raises(SystemExit):
        only_parse_args(["market", "profiles", "--format", "json"])
