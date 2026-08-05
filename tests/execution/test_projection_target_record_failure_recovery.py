import pytest

from onlyalpha.execution import (
    OnlyAppliedRuntimeProjectionRecord,
    OnlyInMemoryAppliedRuntimeProjectionLedger,
    OnlyProjectionApplyStatus,
    OnlyRuntimeProjectionComponent,
)
from tests.execution.support.manager_authority_digest import only_test_runtime_authority_digest
from tests.execution.targets.support import only_test_projection_context, only_test_projection_target_bundle


class _OnlyTestFailOnceAppliedProjectionLedger:
    def __init__(self) -> None:
        self.failed = False

    def get(
        self,
        execution_sequence: int,
        component: OnlyRuntimeProjectionComponent,
    ) -> OnlyAppliedRuntimeProjectionRecord | None:
        del execution_sequence, component
        return None

    def record(self, record: OnlyAppliedRuntimeProjectionRecord) -> None:
        del record
        if not self.failed:
            self.failed = True
            raise RuntimeError("injected Applied Projection record failure")


@pytest.mark.parametrize(
    "component",
    (
        OnlyRuntimeProjectionComponent.POSITION,
        OnlyRuntimeProjectionComponent.FEE,
        OnlyRuntimeProjectionComponent.ACCOUNT,
        OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
        OnlyRuntimeProjectionComponent.VALUATION,
    ),
)
def test_manager_install_survives_ledger_record_failure_and_retry_recovers(
    component: OnlyRuntimeProjectionComponent,
) -> None:
    bundle = only_test_projection_target_bundle()
    context = only_test_projection_context(bundle, component)
    failing_target = bundle.create_targets(_OnlyTestFailOnceAppliedProjectionLedger())[component]
    with pytest.raises(RuntimeError, match="injected Applied Projection record failure"):
        failing_target.apply_execution_projection(context)
    installed = only_test_runtime_authority_digest(bundle.environment)

    ledger = OnlyInMemoryAppliedRuntimeProjectionLedger()
    recovered_target = bundle.create_targets(ledger)[component]
    result = recovered_target.apply_execution_projection(context)
    assert result.status is OnlyProjectionApplyStatus.RECOVERED
    assert len(ledger.records()) == 1
    assert only_test_runtime_authority_digest(bundle.environment) == installed
