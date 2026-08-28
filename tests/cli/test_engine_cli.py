from pathlib import Path

import pytest

from onlyalpha.cli import main, only_parse_args, only_resolve_user_data_root
from tests.scenario.test_scenario_core import _seed_scenario_strategy


def test_user_data_precedence(tmp_path: Path, monkeypatch: object) -> None:
    env_root = tmp_path / "environment"
    cli_root = tmp_path / "cli"
    monkeypatch.setenv("ONLYALPHA_USER_DATA", str(env_root))  # type: ignore[attr-defined]
    assert only_resolve_user_data_root(None) == env_root.resolve()
    assert only_resolve_user_data_root(str(cli_root)) == cli_root.resolve()


@pytest.mark.parametrize("command", ("run", "snapshot"))
def test_legacy_product_mutation_commands_are_absent(command: str) -> None:
    with pytest.raises(SystemExit) as error:
        only_parse_args([command])
    assert error.value.code == 2


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
