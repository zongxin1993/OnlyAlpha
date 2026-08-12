"""Lazy public Runtime exports which avoid Runtime/Cluster import cycles."""

from importlib import import_module

_EXPORTS = {
    "OnlyRuntimeContext": "onlyalpha.runtime.context",
    "OnlyRuntimeContextView": "onlyalpha.runtime.context",
    "OnlyBacktestRuntime": "onlyalpha.runtime.backtest.runtime",
    "OnlyLiveRuntime": "onlyalpha.runtime.live.runtime",
    "OnlyPaperRuntime": "onlyalpha.runtime.paper.runtime",
    "OnlyResearchRuntime": "onlyalpha.runtime.research.runtime",
    "OnlyShadowRuntime": "onlyalpha.runtime.shadow.runtime",
    "OnlySimRuntime": "onlyalpha.runtime.sim.runtime",
    "OnlyRuntime": "onlyalpha.runtime.runtime",
    "OnlyRuntimeOutboxDeliveryError": "onlyalpha.runtime.runtime",
    "OnlyRuntimeRecoveryError": "onlyalpha.runtime.runtime",
    "OnlyRuntimeState": "onlyalpha.runtime.runtime",
    "OnlyRuntimeStatus": "onlyalpha.runtime.runtime",
    "OnlyRuntimeTradeResult": "onlyalpha.runtime.runtime",
    "OnlyRuntimeEventGateDecision": "onlyalpha.runtime.events.gate",
    "OnlyRuntimeEventGateError": "onlyalpha.runtime.events.gate",
    "OnlyRuntimeEventGatePhase": "onlyalpha.runtime.events.gate",
    "OnlyRuntimeEventGateSnapshot": "onlyalpha.runtime.events.gate",
    "OnlyRuntimeEventGateTransitionError": "onlyalpha.runtime.events.gate",
    "OnlyRuntimeEventRouteError": "onlyalpha.runtime.events.gate",
    "OnlyRuntimeEventStageCapacityError": "onlyalpha.runtime.events.gate",
    "OnlyRuntimeRecoveryEventGate": "onlyalpha.runtime.events.gate",
    "OnlySuppressedRuntimeEvent": "onlyalpha.runtime.events.gate",
    "OnlyRuntimeEventRouter": "onlyalpha.runtime.events.router",
    "OnlyCommittedTradeFeeAttribution": "onlyalpha.runtime.reconciliation",
    "OnlyRuntimeLedgerDifference": "onlyalpha.runtime.reconciliation",
    "OnlyRuntimeLedgerReconciliationResult": "onlyalpha.runtime.reconciliation",
    "OnlyRuntimeLedgerReconciliationService": "onlyalpha.runtime.reconciliation",
    "OnlyRuntimeLedgerReconciliationStatus": "onlyalpha.runtime.reconciliation",
    "OnlyRuntimeRecoveryOutcome": "onlyalpha.runtime.recovery.outcome",
    "OnlyRuntimeRecoveryFinalizer": "onlyalpha.runtime.recovery.finalizer",
    "OnlyRuntimeRecoveryFinalizationError": "onlyalpha.runtime.recovery.finalizer",
    "OnlyRuntimeRecoveryFinalizationPhase": "onlyalpha.runtime.recovery.finalizer",
    "OnlyRuntimeRecoveryFinalizationResult": "onlyalpha.runtime.recovery.finalizer",
    "OnlyPostRecoveryAuthorityValidator": "onlyalpha.runtime.recovery.validation",
    "OnlyPostRecoveryCheckStatus": "onlyalpha.runtime.recovery.validation",
    "OnlyPostRecoveryValidationCheck": "onlyalpha.runtime.recovery.validation",
    "OnlyPostRecoveryValidationContext": "onlyalpha.runtime.recovery.validation",
    "OnlyPostRecoveryValidationReport": "onlyalpha.runtime.recovery.validation",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> object:
    try:
        module_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value: object = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
