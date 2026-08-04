from onlyalpha.operations.acceptance.models import OnlyAcceptanceFailureKind, OnlyAcceptanceVerdict
from onlyalpha.operations.acceptance.paper_runner import OnlyPaperAcceptanceRunner


def test_native_abort_and_timeout_are_external_blocks() -> None:
    assert OnlyPaperAcceptanceRunner.classify_runtime_failure(RuntimeError("WORKER_ABORTED BSON")) == (
        OnlyAcceptanceVerdict.BLOCKED,
        "MINIQMT_HISTORICAL_NATIVE_BSON_ABORT",
        OnlyAcceptanceFailureKind.EXTERNAL_PROVIDER_BLOCKED,
    )
    assert OnlyPaperAcceptanceRunner.classify_runtime_failure(TimeoutError("timeout")) == (
        OnlyAcceptanceVerdict.BLOCKED,
        "MINIQMT_HISTORICAL_TIMEOUT",
        OnlyAcceptanceFailureKind.EXTERNAL_PROVIDER_BLOCKED,
    )


def test_unknown_product_failure_is_not_downgraded_to_blocked() -> None:
    assert OnlyPaperAcceptanceRunner.classify_runtime_failure(AssertionError("invariant"))[0] is (
        OnlyAcceptanceVerdict.FAIL
    )
