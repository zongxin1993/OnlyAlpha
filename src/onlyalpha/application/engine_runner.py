"""Application lifecycle policy above the sole OnlyEngine product entry."""

from enum import StrEnum

from onlyalpha.engine import OnlyEngine


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
    def execute(self, engine: OnlyEngine) -> int:
        if only_engine_lifecycle_kind(engine) is OnlyRuntimeLifecycleKind.FINITE:
            return engine.run().exit_code
        try:
            engine.initialize()
            engine.start()
            engine.wait()
            return 0
        except KeyboardInterrupt:
            return 0
        finally:
            engine.stop()

    def snapshot(self, engine: OnlyEngine) -> tuple[dict[str, object], ...]:
        if only_engine_lifecycle_kind(engine) is not OnlyRuntimeLifecycleKind.LONG_LIVED:
            raise ValueError("snapshot requires a LONG_LIVED Runtime configuration")
        try:
            engine.initialize()
            engine.start()
            snapshots: list[dict[str, object]] = []
            for runtime in engine.runtimes:
                store = getattr(runtime, "latest_observation_store", None)
                if store is None:
                    raise RuntimeError(f"{runtime.runtime_type} Runtime has no Observation authority")
                snapshots.extend(item.to_dict() for item in store.list_runtime(runtime.config.runtime_id))
            if not snapshots:
                raise RuntimeError("Historical Warmup completed without a latest Observation")
            return tuple(snapshots)
        finally:
            engine.stop()
