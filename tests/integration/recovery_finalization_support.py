from pathlib import Path

from onlyalpha.config import OnlyRuntimePersistenceConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.fee.broker_contract import only_simulation_zero_broker_fee_contract
from onlyalpha.plugin.descriptor import OnlyPluginOrigin, OnlyPluginOriginType
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from tests.integration.test_engine_recovery_same_bar_continuation import (
    OnlySameBarContinuationTestBrokerFactory,
    _same_bar_config,
    _services,
)


class OnlyAfterCommitCheckpointStore:
    def __init__(self, delegate: OnlyRuntimePersistenceStorePort) -> None:
        self._delegate = delegate
        self._failed = False

    def write_checkpoint(self, checkpoint: object, *, retain_last: int) -> None:
        self._delegate.write_checkpoint(checkpoint, retain_last=retain_last)  # type: ignore[arg-type]
        if not self._failed:
            self._failed = True
            raise RuntimeError("TEST_POST_RECOVERY_AFTER_COMMIT")

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


class OnlyAfterCommitCheckpointStoreFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyRuntimePersistenceStorePort:
        return OnlyAfterCommitCheckpointStore(self._delegate.create(request))  # type: ignore[return-value]


class OnlyValidationMismatchStore:
    def __init__(self, delegate: OnlyRuntimePersistenceStorePort) -> None:
        self._delegate = delegate
        self._recovery_planned = False

    def recovery_records(self, *args: object, **kwargs: object) -> object:
        result = self._delegate.recovery_records(*args, **kwargs)  # type: ignore[arg-type]
        self._recovery_planned = True
        return result

    def records(self, *args: object, **kwargs: object) -> object:
        result = self._delegate.records(*args, **kwargs)  # type: ignore[arg-type]
        return result[1:] if self._recovery_planned else result

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


class OnlyValidationMismatchStoreFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyRuntimePersistenceStorePort:
        return OnlyValidationMismatchStore(self._delegate.create(request))  # type: ignore[return-value]


def only_recovery_services(factory: object | None = None):  # type: ignore[no-untyped-def]
    services = only_default_engine_services(runtime_persistence_store_factory=factory)  # type: ignore[arg-type]
    services.assembler.components.brokers.register(
        OnlySameBarContinuationTestBrokerFactory(),
        origin=OnlyPluginOrigin(OnlyPluginOriginType.TEST, __name__),
    )
    services.assembler.components.broker_fee_contracts.register(
        only_simulation_zero_broker_fee_contract("test-same-bar-broker")
    )
    return services


def only_create_tail_failure(tmp_path: Path, engine_id: OnlyEngineId) -> OnlyEngine:
    engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services(with_fault=True))
    engine.add_cluster(_same_bar_config())
    assert engine.run().status == "FAILED"
    return engine
