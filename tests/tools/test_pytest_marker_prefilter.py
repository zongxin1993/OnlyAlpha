from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.pytest_marker_prefilter import module_may_contain_marker


@pytest.mark.parametrize(
    "source",
    (
        "pytestmark = pytest.mark.recovery\n",
        "@pytest.mark.recovery\nclass TestMarked: pass\n",
        "@pytest.mark.recovery\ndef test_marked(): pass\n",
    ),
)
def test_module_class_and_function_markers_are_discovered(tmp_path: Path, source: str) -> None:
    path = tmp_path / "test_marked.py"
    path.write_text("import pytest\n" + source, encoding="utf-8")

    assert module_may_contain_marker(path, "recovery")


def test_invalid_syntax_fails_open_for_normal_pytest_collection(tmp_path: Path) -> None:
    path = tmp_path / "test_broken.py"
    path.write_text("def broken(:\n", encoding="utf-8")

    assert module_may_contain_marker(path, "recovery")


def test_prefilter_isolates_unmarked_import_failure_and_keeps_item_selection(tmp_path: Path) -> None:
    broken = tmp_path / "test_unrelated.py"
    broken.write_text("raise RuntimeError('unrelated collection failure')\n", encoding="utf-8")
    mixed = tmp_path / "test_mixed.py"
    mixed.write_text(
        "import pytest\n"
        "def test_unmarked(): raise AssertionError('must be deselected')\n"
        "@pytest.mark.recovery\n"
        "def test_marked(): pass\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "pytest",
            str(tmp_path),
            "-q",
            "-m",
            "recovery",
            "-p",
            "scripts.pytest_marker_prefilter",
            "--onlyalpha-prefilter-marker",
            "recovery",
        ),
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed, 1 deselected" in completed.stdout
