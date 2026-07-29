from pathlib import Path

from tests.integration.test_engine_multi_transaction_tail_recovery import (
    test_engine_recovers_ready_prefix_and_unprojected_suffix_then_continues as _run_causal_scenario,
)


def test_ready_and_unprojected_transactions_resolve_at_original_broker_update_points(tmp_path: Path) -> None:
    _run_causal_scenario(tmp_path)
