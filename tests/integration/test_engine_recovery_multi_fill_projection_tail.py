from onlyalpha.domain.identifiers import OnlyEngineId
from tests.execution.support.execution_fault_injection import OnlyTestRuntimePersistenceFault
from tests.integration.virtual_multi_fill_support import (
    OnlyMultiFillFaultStoreFactory,
    only_assert_multi_fill_recovery_equivalence,
)


def test_multi_fill_recovers_projection_ready_tail(tmp_path) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId("multi-fill-projection-tail"),
        factory=OnlyMultiFillFaultStoreFactory(OnlyTestRuntimePersistenceFault.MARK_READY),
    )
