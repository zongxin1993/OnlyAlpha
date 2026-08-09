from onlyalpha.execution.processor import OnlyExecutionProcessor


def test_removed_non_durable_trade_path_is_absent() -> None:
    assert not hasattr(OnlyExecutionProcessor, "_unmigrated_trade")
