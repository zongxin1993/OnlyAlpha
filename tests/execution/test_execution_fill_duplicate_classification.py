from onlyalpha.execution import OnlyExecutionFillClassification, only_classify_execution_fill


def test_duplicate_and_conflict_classification() -> None:
    fingerprint = "a" * 64
    assert (
        only_classify_execution_fill(existing_payload_fingerprint=None, payload_fingerprint=fingerprint)
        is OnlyExecutionFillClassification.NEW
    )
    assert (
        only_classify_execution_fill(existing_payload_fingerprint=fingerprint, payload_fingerprint=fingerprint)
        is OnlyExecutionFillClassification.DUPLICATE
    )
    assert (
        only_classify_execution_fill(existing_payload_fingerprint="b" * 64, payload_fingerprint=fingerprint)
        is OnlyExecutionFillClassification.CONFLICT
    )
