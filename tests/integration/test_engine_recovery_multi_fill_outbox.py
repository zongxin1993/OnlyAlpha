from onlyalpha.domain.identifiers import OnlyEngineId
from tests.integration.virtual_multi_fill_support import (
    OnlyOutboxCheckpointFailureStoreFactory,
    only_assert_multi_fill_recovery_equivalence,
)


def test_multi_fill_recovers_pending_outbox_without_reprojection(tmp_path) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId("multi-fill-outbox"),
        factory=OnlyOutboxCheckpointFailureStoreFactory(),
    )
