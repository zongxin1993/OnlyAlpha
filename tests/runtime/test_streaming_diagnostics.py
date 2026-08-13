from collections import deque
from unittest.mock import Mock

from onlyalpha.data.enums import OnlyMarketDataProcessingStatus
from onlyalpha.runtime.streaming.runtime import OnlyStreamingRuntime


def test_processing_diagnostics_keep_total_count_and_bounded_recent_window() -> None:
    runtime = OnlyStreamingRuntime.__new__(OnlyStreamingRuntime)
    runtime._processing_results = deque(maxlen=3)
    runtime._processing_result_count = 0
    runtime._duplicate_count = 0
    runtime._sequence_gap_count = 0
    results = []

    for index in range(10):
        result = Mock(
            status=OnlyMarketDataProcessingStatus.IGNORED,
            pipeline_result=None,
            update_id=f"update-{index}",
        )
        results.append(result)
        runtime._record_processing_result(Mock(), result)

    assert runtime.processing_result_count == 10
    assert runtime.processing_results == tuple(results[-3:])
    assert len(runtime.processing_results) <= runtime._processing_result_capacity
