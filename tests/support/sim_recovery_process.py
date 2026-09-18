from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from pytest import MonkeyPatch

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.runtime.sim.runtime import OnlySimRuntime
from tests.integration.test_engine_sim_virtual_broker_execution import _engine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("write", "recover"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    patch = MonkeyPatch()
    engine = None
    try:
        engine, _feed, _clock, _user_data = _engine(
            args.root,
            patch,
            engine_id="sim-subprocess-restart",
            checkpoint=True,
        )
        engine.initialize()
        runtime = cast(OnlySimRuntime, engine.runtimes[0])
        engine.start()
        checkpoint = runtime._checkpoint_query.latest_checkpoint(OnlyRuntimeId(runtime.runtime_id))  # type: ignore[attr-defined]
        if checkpoint is None:
            raise RuntimeError("subprocess SIM did not advertise a checkpoint")
        if args.stage == "recover" and not runtime.runtime_recovery_diagnostics:
            raise RuntimeError("subprocess SIM did not enter recovery")
        engine.stop()
        engine.close()
        return 0
    finally:
        if engine is not None:
            engine.close()
        patch.undo()


if __name__ == "__main__":
    raise SystemExit(main())
