"""Offline subprocess fixture for real OS-signal lifecycle tests."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from onlyalpha.application.engine_runner import OnlyEngineApplicationRunner


class _LongLivedEngine:
    def __init__(self) -> None:
        self.engine_id = "signal-subprocess"
        self.state = "CREATED"
        self.cluster_definitions = (SimpleNamespace(runtime=SimpleNamespace(runtime_type="PAPER")),)

    def initialize(self) -> None:
        self.state = "READY"

    def start(self) -> None:
        self.state = "RUNNING"
        print("READY", flush=True)

    def wait(self, timeout: float | None = None) -> None:
        threading.Event().wait(timeout)

    def stop(self) -> None:
        if self.state == "STOPPED":
            return
        self.state = "STOPPED"
        print("ENGINE_STOPPED", flush=True)
        owned = sorted(thread.name for thread in threading.enumerate() if thread.name.startswith("onlyalpha-"))
        print(f"ONLYALPHA_THREADS={owned}", flush=True)


def main() -> int:
    engine = _LongLivedEngine()
    code = OnlyEngineApplicationRunner().execute(engine)  # type: ignore[arg-type]
    print(f"EXIT_CODE={code}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
