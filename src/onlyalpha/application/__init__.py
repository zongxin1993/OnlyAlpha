"""Lazy stable application exports without unrelated runtime dependency loading."""

from importlib import import_module

_EXPORTS = {
    "OnlyCalculationEquivalenceCertificationApplicationService": "onlyalpha.application.calculation_equivalence",
    "OnlyCalculationEquivalenceCertificationProfileAuthority": "onlyalpha.application.calculation_equivalence",
    "OnlyEngineApplicationRunner": "onlyalpha.application.engine_runner",
    "OnlyEngineInspectionService": "onlyalpha.application.engine_inspection",
    "OnlyEconomicBaseline": "onlyalpha.application.runtime_inspection",
    "OnlyHistoricalWarmupInspection": "onlyalpha.application.runtime_inspection",
    "OnlyRuntimeLifecycleKind": "onlyalpha.application.engine_runner",
    "OnlyProductCommandAdmissionAuthority": "onlyalpha.application.product_command_authority",
    "OnlyProductCommandAuthorityError": "onlyalpha.application.product_command_authority",
    "OnlyProductCommandBindingState": "onlyalpha.application.product_command_authority",
    "OnlyProductCommandBindingVerification": "onlyalpha.application.product_command_authority",
    "OnlyProductCommandReceiptAuthority": "onlyalpha.application.product_command_authority",
    "OnlyProductCommandAdmissionV1": "onlyalpha.application.product_command_receipt",
    "OnlyProductCommandId": "onlyalpha.application.product_command_receipt",
    "OnlyProductCommandKind": "onlyalpha.application.product_command_receipt",
    "OnlyProductCommandOutcomeKind": "onlyalpha.application.product_command_receipt",
    "OnlyProductCommandOutcomeRef": "onlyalpha.application.product_command_receipt",
    "OnlyProductCommandReceipt": "onlyalpha.application.product_command_receipt",
    "OnlyStreamingRuntimeInspectionSnapshot": "onlyalpha.application.runtime_inspection",
    "OnlySubscriptionInspection": "onlyalpha.application.runtime_inspection",
    "only_engine_lifecycle_kind": "onlyalpha.application.engine_runner",
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
