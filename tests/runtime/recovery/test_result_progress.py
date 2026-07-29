from onlyalpha.runtime.backtest.result_progress import OnlyBacktestResultProgress


def test_result_progress_checkpoint_round_trip_restores_complete_business_prefix() -> None:
    original = OnlyBacktestResultProgress()
    original.restore_checkpoint(
        {
            "applied_count": 7,
            "attempted_count": 11,
            "business_failures": [],
            "duplicate_count": 2,
            "failed_count": 1,
            "gap_detected_count": 3,
            "last_market_processing_sequence": 11,
            "processed_bar_count": 7,
            "quality_flags": ["DUPLICATE", "GAP_DETECTED", "UNEXPECTED_GAP"],
            "rejected_count": 1,
        }
    )
    restored = OnlyBacktestResultProgress()
    restored.restore_checkpoint(original.capture_checkpoint())

    assert restored.snapshot() == original.snapshot()
