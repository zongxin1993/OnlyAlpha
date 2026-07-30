from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyExecutionCommitCoordinator,
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionTarget,
    OnlyExecutionRecoveryResult,
    OnlyExecutionRecoveryService,
    OnlyInMemoryAppliedProjectionLedger,
)
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from tests.execution.support.execution_authority_digest import OnlyExecutionAuthorityDigest
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceAppliedProjectionLedger,
    OnlyFailOnceExecutionProjectionTarget,
)
from tests.execution.support.generic_t0_trade_harness import OnlyTestGenericT0Scenario
from tests.execution.support.manager_authority_digest import only_test_runtime_authority_digest
from tests.execution.targets.support import OnlyTestProjectionTargetBundle, only_test_projection_target_bundle


class OnlyRealExecutionRecoveryHarness:
    def __init__(
        self,
        bundle: OnlyTestProjectionTargetBundle,
        targets: Mapping[OnlyExecutionProjectionComponent, OnlyExecutionProjectionTarget],
        applied_ledger: OnlyInMemoryAppliedProjectionLedger,
    ) -> None:
        self.bundle = bundle
        self.applied_ledger = applied_ledger
        self.targets = dict(targets)
        self.coordinator = self._coordinator(self.targets)
        self.recovery_service = OnlyExecutionRecoveryService(self.coordinator)

    @classmethod
    def create(
        cls,
        *,
        store: OnlyRuntimePersistenceStorePort | None = None,
        scenario: OnlyTestGenericT0Scenario | None = None,
        target_fault: tuple[OnlyExecutionProjectionComponent, str] | None = None,
        ledger_fault: OnlyExecutionProjectionComponent | None = None,
        long_close: bool = False,
    ) -> OnlyRealExecutionRecoveryHarness:
        bundle = only_test_projection_target_bundle(scenario, store, long_close=long_close)
        ledger = OnlyInMemoryAppliedProjectionLedger()
        target_ledger = ledger if ledger_fault is None else OnlyFailOnceAppliedProjectionLedger(ledger, ledger_fault)
        targets = bundle.create_targets(target_ledger)
        if target_fault is not None:
            component, position = target_fault
            targets[component] = OnlyFailOnceExecutionProjectionTarget(
                targets[component],
                fail_before=position == "before",
                fail_after=position == "after",
            )
        return cls(bundle, targets, ledger)

    @property
    def transaction_store(self) -> OnlyRuntimePersistenceStorePort:
        return self.bundle.transaction_store

    def recover(self) -> OnlyExecutionRecoveryResult:
        return self.recovery_service.recover(self.bundle.transaction.runtime_id)

    def authority_digest(self) -> OnlyExecutionAuthorityDigest:
        return OnlyExecutionAuthorityDigest(
            only_test_runtime_authority_digest(self.bundle.environment),
            self.applied_ledger.records(),
            self.transaction_store.records(self.bundle.transaction.runtime_id),
            self.transaction_store.outbox_records(self.bundle.transaction.runtime_id),
        )

    def manager_digest(self) -> object:
        digest = only_test_runtime_authority_digest(self.bundle.environment)
        return replace(digest, journal=(), event_bus=())

    def rebuild_with_clean_ledger(self) -> None:
        self.applied_ledger = OnlyInMemoryAppliedProjectionLedger()
        self.targets = self.bundle.create_targets(self.applied_ledger)
        self.coordinator = self._coordinator(self.targets)
        self.recovery_service = OnlyExecutionRecoveryService(self.coordinator)

    def _coordinator(
        self,
        targets: Mapping[OnlyExecutionProjectionComponent, OnlyExecutionProjectionTarget],
    ) -> OnlyExecutionCommitCoordinator:
        runtime = self.bundle.environment.runtime
        return OnlyExecutionCommitCoordinator(
            commit_port=self.transaction_store,
            query_port=self.transaction_store,
            projection_state_port=self.transaction_store,
            projection_applier=OnlyExecutionProjectionApplier(targets),
            now=lambda: OnlyTimestamp.from_unix_nanos(runtime.clock.timestamp_ns()),
        )


__all__ = ["OnlyRealExecutionRecoveryHarness"]
