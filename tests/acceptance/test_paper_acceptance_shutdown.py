import subprocess
import sys
from pathlib import Path


def test_acceptance_runner_uses_engine_lifecycle_and_finally_shutdown() -> None:
    source = Path("src/onlyalpha/operations/acceptance/paper_runner.py").read_text(encoding="utf-8")
    assert "engine.initialize()" in source
    assert "engine.start()" in source
    assert "engine.stop()" in source
    assert "engine.close()" in source
    assert "runtime.initialize()" not in source
    assert "runtime.start()" not in source
    assert "_services" not in source


def test_direct_script_entry_can_import_repository_examples() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_paper_real_acceptance.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
