"""Risk/Position views must import in either fresh-process order."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("first", ["onlyalpha.risk.views", "onlyalpha.position.views"])
def test_views_import_in_a_fresh_interpreter_without_preload(first: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {first}; import onlyalpha.risk.views; import onlyalpha.position.views"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
