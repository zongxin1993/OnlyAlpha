from pathlib import Path

from onlyalpha.cli import main, only_parse_args, only_resolve_config_paths, only_resolve_user_data_root

CONFIG = "examples/clusters/macd/config.yaml"
FAST_CONFIG = "examples/clusters/macd_fast/config.yaml"


def test_repeated_config_order_is_preserved_and_deduplicated() -> None:
    args = only_parse_args(["run", "--config", FAST_CONFIG, "--config", CONFIG, "--config", FAST_CONFIG])
    paths = only_resolve_config_paths(args)
    assert [item.name for item in paths] == ["config.yaml", "config.yaml"]
    assert "macd_fast" in str(paths[0])
    assert "macd/config" in str(paths[1])


def test_user_data_precedence(tmp_path: Path, monkeypatch: object) -> None:
    env_root = tmp_path / "environment"
    cli_root = tmp_path / "cli"
    monkeypatch.setenv("ONLYALPHA_USER_DATA", str(env_root))  # type: ignore[attr-defined]
    assert only_resolve_user_data_root(None) == env_root.resolve()
    assert only_resolve_user_data_root(str(cli_root)) == cli_root.resolve()


def test_dry_run_does_not_create_run_output(tmp_path: Path) -> None:
    assert main(["run", "--config", CONFIG, "--user-data", str(tmp_path), "--dry-run"]) == 0
    assert not (tmp_path / "runs").exists()
