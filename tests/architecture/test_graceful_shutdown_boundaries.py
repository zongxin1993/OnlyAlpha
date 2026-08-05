from pathlib import Path


def test_process_signal_handlers_exist_only_at_application_boundary() -> None:
    production = Path("src/onlyalpha")
    offenders = [
        path
        for path in production.rglob("*.py")
        if path.as_posix() != "src/onlyalpha/application/stop_controller.py"
        and (
            "signal.signal(" in path.read_text(encoding="utf-8")
            or "signal.getsignal(" in path.read_text(encoding="utf-8")
        )
    ]
    assert offenders == []


def test_onlyalpha_owned_threads_are_not_daemon_escape_hatches_and_joins_are_bounded() -> None:
    roots = (Path("src/onlyalpha"), Path("packages/provider/onlyalpha-plugin-miniqmt/src"))
    sources = {path: path.read_text(encoding="utf-8") for root in roots for path in root.rglob("*.py")}
    assert [path for path, source in sources.items() if "daemon=True" in source] == []
    assert [path for path, source in sources.items() if ".join()" in source] == []


def test_engine_shutdown_delegates_cluster_ownership_to_runtime_close() -> None:
    source = Path("src/onlyalpha/engine/engine.py").read_text(encoding="utf-8")
    stop = source[source.index("    def stop(self) -> None:") : source.index("    def close(self) -> None:")]
    assert "runtime.close()" in stop
    assert "stop_cluster" not in stop
