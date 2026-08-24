import json
from pathlib import Path

import pytest

from onlyalpha.application.engine_runner import OnlyEngineApplicationRunner
from onlyalpha.cli import main, only_parse_args, only_resolve_config_paths, only_resolve_user_data_root
from onlyalpha.config import OnlyClusterRunConfig
from tests.runtime_runner import only_migrate_cluster_to_strategy
from tests.scenario.test_scenario_core import _seed_scenario_strategy

CONFIG = "tests/fixtures/legacy_macd/cluster.json"
FAST_CONFIG = "tests/fixtures/legacy_macd/cluster_fast.json"


def _p9_config(tmp_path: Path) -> Path:
    migrated = only_migrate_cluster_to_strategy(OnlyClusterRunConfig.load(CONFIG), tmp_path)
    payload = json.loads(Path(CONFIG).read_text(encoding="utf-8"))
    payload["strategy"] = {"fingerprint": migrated.strategy.fingerprint}
    payload["factors"] = []
    payload["data_sources"][0]["extensions"]["market_config"] = str(
        Path("tests/fixtures/legacy_macd/synthetic_market.yaml").resolve()
    )
    target = tmp_path / "cluster.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


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
    config = _p9_config(tmp_path)
    assert main(["run", "--config", str(config), "--user-data", str(tmp_path), "--dry-run"]) == 0
    assert not (tmp_path / "runs").exists()


def test_snapshot_runtime_failure_is_reported_without_a_traceback(
    tmp_path: Path, monkeypatch: object, capsys: object
) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        OnlyEngineApplicationRunner,
        "snapshot",
        lambda self, engine: (_ for _ in ()).throw(RuntimeError("warmup failed closed")),
    )
    config = _p9_config(tmp_path)
    assert main(["snapshot", "--config", str(config), "--user-data", str(tmp_path)]) == 2
    assert "onlyalpha: warmup failed closed" in capsys.readouterr().out  # type: ignore[attr-defined]


def test_scenario_validate_run_and_retired_profile_query_cli(tmp_path: Path, capsys: object) -> None:
    source = Path("tests/fixtures/scenarios/generic_t0_cash.yaml")
    strategy_fingerprint = _seed_scenario_strategy(tmp_path)
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(source.read_text(encoding="utf-8").replace("a" * 64, strategy_fingerprint), encoding="utf-8")
    assert main(["scenario", "validate", str(scenario), "--format", "json"]) == 0
    assert '"valid": true' in capsys.readouterr().out  # type: ignore[attr-defined]

    assert main(["scenario", "run", str(scenario), "--user-data", str(tmp_path), "--format", "json"]) == 0
    assert '"status": "PASSED"' in capsys.readouterr().out  # type: ignore[attr-defined]

    with pytest.raises(SystemExit):
        only_parse_args(["market", "profiles", "--format", "json"])
