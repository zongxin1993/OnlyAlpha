from __future__ import annotations

import os
import signal
import subprocess
import sys

import pytest


def _start() -> subprocess.Popen[str]:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        [sys.executable, "-m", "tests.support.long_lived_cli"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        creationflags=creationflags,
    )


def _assert_shutdown(process: subprocess.Popen[str], expected_code: int, signum: int) -> None:
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "READY"
    started = __import__("time").monotonic()
    process.send_signal(signum)
    output, _ = process.communicate(timeout=3)
    assert __import__("time").monotonic() - started < 3
    assert process.returncode == expected_code
    assert "ENGINE_STOPPED" in output
    assert "ONLYALPHA_THREADS=[]" in output
    assert "Traceback" not in output


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal contract")
@pytest.mark.parametrize(("signum", "expected"), ((signal.SIGINT, 130), (signal.SIGTERM, 143)))
def test_posix_signal_gracefully_stops_long_lived_application(signum: signal.Signals, expected: int) -> None:
    _assert_shutdown(_start(), expected, signum)


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="Windows console-event contract")
def test_windows_ctrl_break_gracefully_stops_long_lived_application() -> None:
    # CREATE_NEW_PROCESS_GROUP gives the child a targetable console process group;
    # CTRL_BREAK_EVENT is reliable for that group, unlike reusing a POSIX signal API.
    _assert_shutdown(_start(), 130, signal.CTRL_BREAK_EVENT)
