from pathlib import Path

from tests.integration.test_engine_continuous_restart import only_assert_engine_restart_equivalence


def test_checkpointed_result_progress_preserves_full_result_prefix(tmp_path: Path) -> None:
    only_assert_engine_restart_equivalence(tmp_path)
