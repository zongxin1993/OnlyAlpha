from __future__ import annotations

from pathlib import Path

import onlyalpha_api.artifact_main as artifact_server
import onlyalpha_api.main as server
import pytest


def test_servers_require_explicit_roots() -> None:
    with pytest.raises(SystemExit) as full:
        server.main([])
    with pytest.raises(SystemExit) as portable:
        artifact_server.main([])
    assert full.value.code == portable.value.code == 2


def test_portable_server_defaults_to_loopback_and_needs_no_postgres(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app, *, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        captured.update(app=app, host=host, port=port)

    monkeypatch.delenv("ONLYALPHA_POSTGRES_DSN", raising=False)
    monkeypatch.setattr(artifact_server.uvicorn, "run", fake_run)
    assert artifact_server.main(["--artifact-root", str(tmp_path)]) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
    assert captured["app"] is not None
    assert Path(tmp_path).is_dir()
