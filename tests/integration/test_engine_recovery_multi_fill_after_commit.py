from onlyalpha.domain.identifiers import OnlyEngineId
from tests.execution.support.execution_fault_injection import OnlyTestRuntimePersistenceFault
from tests.integration.virtual_multi_fill_support import (
    OnlyMultiFillFaultStoreFactory,
    only_assert_multi_fill_recovery_equivalence,
)


def test_multi_fill_recovers_committed_unprojected_first_fill(tmp_path) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId("multi-fill-after-commit"),
        factory=OnlyMultiFillFaultStoreFactory(OnlyTestRuntimePersistenceFault.AFTER_COMMIT),
    )
