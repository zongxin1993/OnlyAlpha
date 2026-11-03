"""Operator wrapper guards only; real namespace/session behavior is tested by native PostgreSQL lanes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import database

IDENTITY = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def setup_operator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[MagicMock, MagicMock, MagicMock]:
    selected = database.OnlyResearchSemanticStoreId(IDENTITY)
    verifier = MagicMock(spec=["assert_compatible"])
    monkeypatch.setattr(database, "_verifier", lambda _dsn: verifier)
    monkeypatch.setattr(database, "only_assert_supported_postgres_server", lambda _dsn: None)
    monkeypatch.setattr(database, "_selected_native_backend", lambda _explicit: tmp_path / "native-backend")
    binding = MagicMock()
    binding.load_semantic_store_id.return_value = selected
    monkeypatch.setattr(database, "OnlyPostgresResearchDeploymentStore", lambda _dsn: binding)
    local = MagicMock()
    local.load_verified.return_value = selected
    monkeypatch.setattr(database, "OnlyResearchSemanticStoreIdentity", lambda _root: local)
    run = MagicMock(
        return_value=subprocess.CompletedProcess(
            [], 0, json.dumps({"schema_version": 1, "semantic_store_id": IDENTITY}), ""
        )
    )
    monkeypatch.setattr(database.subprocess, "run", run)
    return binding, local, run


@pytest.mark.parametrize("manual", [False, True])
def test_explicit_extensions_reuse_the_same_guard_and_only_the_selected_native_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, manual: bool
) -> None:
    binding, local, run = setup_operator(monkeypatch, tmp_path)
    operation = database._extend_manual_backtest if manual else database._extend_strategy_research
    assert operation("controlled-dsn", tmp_path, tmp_path / "native-backend") == IDENTITY
    assert run.call_args.args[0] == [
        str(tmp_path / "native-backend"),
        "--extend-manual-backtest-namespace" if manual else "--extend-strategy-research-namespace",
        str(tmp_path),
    ]
    assert run.call_args.kwargs["env"]["ONLYALPHA_POSTGRES_DSN"] == "controlled-dsn"
    assert binding.load_semantic_store_id.call_count == 2
    assert local.load_verified.call_count == 2
    binding.initialize.assert_not_called()


@pytest.mark.parametrize("mismatch", ["before-local", "after-local", "after-database", "native-reply"])
def test_manual_extension_refuses_namespace_substitution_and_never_initializes_a_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mismatch: str
) -> None:
    binding, local, run = setup_operator(monkeypatch, tmp_path)
    original = database.OnlyResearchSemanticStoreId(IDENTITY)
    foreign = database.OnlyResearchSemanticStoreId(OTHER)
    if mismatch == "before-local":
        local.load_verified.return_value = foreign
    elif mismatch == "after-local":
        local.load_verified.side_effect = [original, foreign]
    elif mismatch == "after-database":
        binding.load_semantic_store_id.side_effect = [original, foreign]
    else:
        run.return_value.stdout = json.dumps({"schema_version": 1, "semantic_store_id": OTHER})
    with pytest.raises(RuntimeError, match="DEPLOYMENT_MISMATCH"):
        database._extend_manual_backtest("controlled-dsn", tmp_path)
    assert run.call_count == (0 if mismatch == "before-local" else 1)
    binding.initialize.assert_not_called()


def test_unknown_native_extension_outcome_is_not_retried_or_replaced_in_python(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binding, _local, run = setup_operator(monkeypatch, tmp_path)
    run.side_effect = subprocess.CalledProcessError(1, "selected-native-owner")
    with pytest.raises(subprocess.CalledProcessError):
        database._extend_manual_backtest("controlled-dsn", tmp_path)
    assert run.call_count == 1
    binding.initialize.assert_not_called()


def test_operator_cli_exposes_the_explicit_manual_command_without_starting_services(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        database.OnlyPostgresConfig, "from_environment", lambda _name: type("Config", (), {"dsn": "controlled-dsn"})()
    )
    monkeypatch.setattr(database, "_authority", lambda _dsn: None)
    monkeypatch.setattr(database, "_verifier", lambda _dsn: None)
    extend = MagicMock(return_value=IDENTITY)
    monkeypatch.setattr(database, "_extend_manual_backtest", extend)
    monkeypatch.setattr(
        database.sys,
        "argv",
        [
            "database",
            "extend-manual-backtest",
            "--user-data-root",
            str(tmp_path),
            "--native-backend",
            str(tmp_path / "native"),
        ],
    )
    assert database.main() == 0
    extend.assert_called_once_with("controlled-dsn", tmp_path, tmp_path / "native")
    assert json.loads(capsys.readouterr().out) == {"semantic_store_id": IDENTITY}
