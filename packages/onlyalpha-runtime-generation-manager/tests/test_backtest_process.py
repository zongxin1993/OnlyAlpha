from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.backtest.errors import OnlyBacktestError


def test_native_transport_refuses_wrong_reply_identity_and_never_retries(tmp_path: Path) -> None:
    from onlyalpha_runtime_generation_manager.backtest_process import OnlyNativeBacktestProcess

    executable = tmp_path / "peer"
    executable.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nr=json.loads(sys.stdin.readline());print(json.dumps({'protocol':'onlyalpha.backtest.driver/1','sequence':9,'payload':{}}),flush=True);sys.stdin.read()\n"
    )
    executable.chmod(0o700)
    with pytest.raises(OnlyBacktestError, match="BACKTEST_NATIVE_PROTOCOL_MISMATCH"):
        OnlyNativeBacktestProcess(executable, {}, tmp_path / "runtime", tmp_path / "stderr.log")


def test_native_transport_does_not_treat_eof_as_empty_success(tmp_path: Path) -> None:
    from onlyalpha_runtime_generation_manager.backtest_process import OnlyNativeBacktestProcess

    executable = tmp_path / "peer"
    executable.write_text("#!/usr/bin/env python3\nimport sys\nsys.stdin.readline()\n")
    executable.chmod(0o700)
    with pytest.raises(OnlyBacktestError, match="BACKTEST_NATIVE_OUTCOME_UNKNOWN"):
        OnlyNativeBacktestProcess(executable, {}, tmp_path / "runtime", tmp_path / "stderr.log")


@pytest.mark.parametrize(
    "reply",
    (
        '{"protocol":"onlyalpha.backtest.driver/1","sequence":0,"sequence":0,"payload":{}}',
        '{"protocol":"onlyalpha.backtest.driver/1","sequence":0,"payload":{"value":NaN}}',
        '{"protocol":"onlyalpha.backtest.driver/1","sequence":true,"payload":{}}',
    ),
)
def test_native_transport_rejects_ambiguous_or_nonfinite_frames(tmp_path: Path, reply: str) -> None:
    from onlyalpha_runtime_generation_manager.backtest_process import OnlyNativeBacktestProcess

    executable = tmp_path / "peer"
    executable.write_text(
        "#!/usr/bin/env python3\nimport sys\nsys.stdin.readline()\nprint("
        + repr(reply)
        + ",flush=True)\nsys.stdin.read()\n"
    )
    executable.chmod(0o700)
    with pytest.raises(OnlyBacktestError, match="BACKTEST_NATIVE_PROTOCOL_MISMATCH"):
        OnlyNativeBacktestProcess(executable, {}, tmp_path / "runtime", tmp_path / "stderr.log")
