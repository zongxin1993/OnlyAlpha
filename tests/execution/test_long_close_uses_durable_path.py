from onlyalpha.execution import OnlyExecutionEventDeliveryMode, OnlyExecutionProcessingStatus, OnlyExecutionProcessor
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def test_generic_t0_long_close_never_calls_unmigrated_trade(monkeypatch) -> None:
    environment, context, _ = only_test_generic_t0_long_close_context()

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("GENERIC_T0_CASH SELL CLOSE reached _unmigrated_trade")

    monkeypatch.setattr(OnlyExecutionProcessor, "_unmigrated_trade", forbidden)
    result = environment.runtime.execution_processor.process(context.update)

    assert result.status is OnlyExecutionProcessingStatus.APPLIED
    assert result.delivery_intent.mode is OnlyExecutionEventDeliveryMode.DURABLE_OUTBOX
    assert result.delivery_intent.committed_execution_sequence == 2
    records = environment.runtime.execution_transaction_query.records(environment.runtime.config.runtime_id)
    assert len(records) == 2
    assert records[-1].fact.order_side.value == "SELL"
    assert records[-1].projection_ready
