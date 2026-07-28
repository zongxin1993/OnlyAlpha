import pytest

from onlyalpha.execution import (
    OnlyAppliedProjectionRecord,
    OnlyExecutionProjectionComponent,
    OnlyInMemoryAppliedProjectionLedger,
    OnlyProjectionApplyStatus,
)
from tests.execution.support.manager_authority_digest import only_test_runtime_authority_digest
from tests.execution.targets.support import only_test_projection_context, only_test_projection_target_bundle


class _OnlyTestFailOnceAppliedProjectionLedger:
    def __init__(self) -> None:
        self.failed = False

    def get(
        self,
        execution_sequence: int,
        component: OnlyExecutionProjectionComponent,
    ) -> OnlyAppliedProjectionRecord | None:
        del execution_sequence, component
        return None

    def record(self, record: OnlyAppliedProjectionRecord) -> None:
        del record
        if not self.failed:
            self.failed = True
            raise RuntimeError("injected Applied Projection record failure")


@pytest.mark.parametrize(
    "component",
    (
        OnlyExecutionProjectionComponent.POSITION,
        OnlyExecutionProjectionComponent.FEE,
        OnlyExecutionProjectionComponent.ACCOUNT,
        OnlyExecutionProjectionComponent.STRATEGY_LEDGER,
        OnlyExecutionProjectionComponent.VALUATION,
    ),
)
def test_manager_install_survives_ledger_record_failure_and_retry_recovers(
    component: OnlyExecutionProjectionComponent,
) -> None:
    bundle = only_test_projection_target_bundle()
    context = only_test_projection_context(bundle, component)
    failing_target = bundle.create_targets(_OnlyTestFailOnceAppliedProjectionLedger())[component]
    with pytest.raises(RuntimeError, match="injected Applied Projection record failure"):
        failing_target.apply_execution_projection(context)
    installed = only_test_runtime_authority_digest(bundle.environment)

    ledger = OnlyInMemoryAppliedProjectionLedger()
    recovered_target = bundle.create_targets(ledger)[component]
    result = recovered_target.apply_execution_projection(context)
    assert result.status is OnlyProjectionApplyStatus.RECOVERED
    assert len(ledger.records()) == 1
    assert only_test_runtime_authority_digest(bundle.environment) == installed
