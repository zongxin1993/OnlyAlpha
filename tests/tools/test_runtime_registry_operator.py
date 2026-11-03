"""Wire guard tests only; real filesystem/PG initialization has a separate native lane."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from scripts.native_web_e2e import initialize_runtime_registry


def reply(monkeypatch: pytest.MonkeyPatch, raw: str) -> Mock:
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=raw))
    monkeypatch.setattr("scripts.native_web_e2e.subprocess.run", run)
    return run


def test_runtime_initialization_calls_only_the_selected_native_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = reply(monkeypatch, json.dumps({"schema_version": 1, "active_for_new_work": None, "states": {}}))
    initialize_runtime_registry(tmp_path / "backend", tmp_path / "resources", tmp_path / "data", "explicit-dsn")
    assert run.call_args.args[0] == [
        str(tmp_path / "backend"),
        "--initialize-fresh-runtime-registry",
        str(tmp_path / "data"),
        str(tmp_path / "resources/schema"),
    ]
    assert run.call_args.kwargs["env"]["ONLYALPHA_POSTGRES_DSN"] == "explicit-dsn"
    assert run.call_args.kwargs["check"] is True
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": True, "active_for_new_work": None, "states": {}},
        {"schema_version": 1, "active_for_new_work": "a" * 64, "states": {}},
        {"schema_version": 1, "active_for_new_work": None, "states": {"a": "READY"}},
        {"schema_version": 1, "active_for_new_work": None, "states": []},
        {"schema_version": 1, "states": {}},
        {"schema_version": 1, "active_for_new_work": None, "states": {}, "granted": True},
    ],
)
def test_runtime_initialization_refuses_nonempty_or_malformed_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: dict[str, Any]
) -> None:
    run = reply(monkeypatch, json.dumps(value))
    with pytest.raises(ValueError, match="RUNTIME_REGISTRY_NATIVE_RESPONSE_INVALID"):
        initialize_runtime_registry(tmp_path / "backend", tmp_path, tmp_path / "data", "explicit-dsn")
    assert run.call_count == 1 and not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema_version":true,"schema_version":1,"active_for_new_work":null,"states":{}}',
        " " * 32769,
    ],
)
def test_runtime_initialization_rejects_duplicate_or_oversized_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: str
) -> None:
    reply(monkeypatch, raw)
    with pytest.raises(ValueError, match="RUNTIME_REGISTRY_NATIVE_RESPONSE_INVALID"):
        initialize_runtime_registry(tmp_path / "backend", tmp_path, tmp_path / "data", "explicit-dsn")


def test_uncertain_native_initialization_never_retries_or_creates_python_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = reply(monkeypatch, "")
    run.side_effect = subprocess.CalledProcessError(1, "selected-native-owner")
    with pytest.raises(subprocess.CalledProcessError):
        initialize_runtime_registry(tmp_path / "backend", tmp_path, tmp_path / "data", "explicit-dsn")
    assert run.call_count == 1 and not (tmp_path / "data").exists()
