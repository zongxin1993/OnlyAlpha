from __future__ import annotations

from pathlib import Path

import onlyalpha_api.main as server
import pytest


def test_server_requires_explicit_artifact_root() -> None:
    with pytest.raises(SystemExit) as caught:
        server.main([])
    assert caught.value.code == 2


def test_server_defaults_to_loopback_and_composes_read_only_store(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app, *, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        captured.update(app=app, host=host, port=port)

    monkeypatch.setattr(server.uvicorn, "run", fake_run)
    assert server.main(["--artifact-root", str(tmp_path)]) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
    assert captured["app"] is not None
    assert Path(tmp_path).is_dir()
