"""Application lifecycle policy above the sole OnlyEngine product entry."""

from __future__ import annotations

import sys
from collections.abc import Callable
from enum import StrEnum
from typing import cast

from onlyalpha.engine import OnlyEngine
from onlyalpha.runtime.runtime import OnlyRuntime

from .stop_controller import (
    OnlyApplicationShutdownReason,
    OnlyApplicationStopController,
    OnlyForcedExitPort,
)


class OnlyRuntimeLifecycleKind(StrEnum):
    FINITE = "FINITE"
    LONG_LIVED = "LONG_LIVED"


def only_engine_lifecycle_kind(engine: OnlyEngine) -> OnlyRuntimeLifecycleKind:
    modes = {config.runtime.runtime_type for config in engine.cluster_definitions}
    if not modes:
        raise ValueError("Engine requires at least one Cluster definition")
    kinds = {
        OnlyRuntimeLifecycleKind.FINITE if mode == "BACKTEST" else OnlyRuntimeLifecycleKind.LONG_LIVED for mode in modes
    }
    if len(kinds) != 1:
        raise ValueError("FINITE and LONG_LIVED Runtime configurations cannot share one Engine execution")
    return next(iter(kinds))


class OnlyEngineApplicationRunner:
    def __init__(
        self,
        *,
        poll_interval: float = 0.25,
        forced_exit: OnlyForcedExitPort | None = None,
        message_writer: Callable[[str], None] | None = None,
    ) -> None:
        if not 0.1 <= poll_interval <= 0.5:
            raise ValueError("long-lived Engine poll interval must be between 0.1 and 0.5 seconds")
        self._poll_interval = poll_interval
        self._forced_exit = forced_exit
        self._message_writer = message_writer or (lambda message: print(message, file=sys.stderr, flush=True))

    def execute(self, engine: OnlyEngine) -> int:
        if only_engine_lifecycle_kind(engine) is OnlyRuntimeLifecycleKind.FINITE:
            return engine.run().exit_code
        controller = OnlyApplicationStopController(self._forced_exit)
        primary_failure: BaseException | None = None
        shutdown_failure: BaseException | None = None
        controller.install()
        try:
            engine.initialize()
            if not controller.stop_requested:
                engine.start()
                self._message_writer(f"OnlyAlpha Engine running: engine_id={engine.engine_id}")
            while not controller.stop_requested:
                engine.wait(timeout=self._poll_interval)
        except KeyboardInterrupt:
            controller.request_stop(OnlyApplicationShutdownReason.KEYBOARD_INTERRUPT)
        except BaseException as exc:
            primary_failure = exc
        finally:
            if controller.stop_requested:
                reason = controller.shutdown_reason
                self._message_writer(
                    f"OnlyAlpha shutdown requested: reason={reason.value if reason is not None else 'UNKNOWN'}"
                )
            try:
                engine.stop()
            except KeyboardInterrupt:
                controller.request_stop(OnlyApplicationShutdownReason.KEYBOARD_INTERRUPT)
            except BaseException as exc:
                shutdown_failure = exc
            finally:
                controller.restore()
        if primary_failure is not None:
            if shutdown_failure is not None:
                primary_failure.add_note(
                    f"Engine shutdown also failed: {type(shutdown_failure).__name__}: {shutdown_failure}"
                )
            raise primary_failure
        if shutdown_failure is not None:
            raise shutdown_failure
        if controller.stop_requested:
            self._message_writer("OnlyAlpha shutdown completed")
        return controller.exit_code

    def snapshot(self, engine: OnlyEngine) -> tuple[dict[str, object], ...]:
        if only_engine_lifecycle_kind(engine) is not OnlyRuntimeLifecycleKind.LONG_LIVED:
            raise ValueError("snapshot requires a LONG_LIVED Runtime configuration")
        try:
            engine.initialize()
            engine.start()
            snapshots: list[dict[str, object]] = []
            for runtime_product in engine.runtimes:
                runtime = cast(OnlyRuntime, runtime_product)
                store = getattr(runtime, "latest_observation_store", None)
                if store is None:
                    raise RuntimeError(f"{runtime.runtime_type} Runtime has no Observation authority")
                snapshots.extend(item.to_dict() for item in store.list_runtime(runtime.config.runtime_id))
            if not snapshots:
                raise RuntimeError("Historical Warmup completed without a latest Observation")
            return tuple(snapshots)
        finally:
            engine.stop()
