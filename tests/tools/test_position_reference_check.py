import copy

import pytest

from scripts.position_reference_check import compare_native_outputs, reference_outputs


def test_python_position_and_close_cost_match_independent_literals() -> None:
    observed = reference_outputs()
    compare_native_outputs(observed)
    changed = copy.deepcopy(observed)
    changed[0]["case"] = "foreign-case"
    with pytest.raises(AssertionError, match="POSITION_NATIVE_PYTHON_MISMATCH"):
        compare_native_outputs(changed)
