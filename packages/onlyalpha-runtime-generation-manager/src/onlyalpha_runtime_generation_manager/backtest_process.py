"""Owned, bounded native Backtest channel; an uncertain command is never retried."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from onlyalpha.backtest.errors import OnlyBacktestError, OnlyBacktestErrorPhase

PROTOCOL = "onlyalpha.backtest.driver/1"
MAX_FRAME = 32 * 1024 * 1024


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate native response field")
        result[key] = value
    return result


def _constant(_: str) -> Any:
    raise ValueError("non-finite native response number")


class OnlyNativeBacktestProcess:
    def __init__(
        self, executable: Path, plan: dict[str, Any], root: Path, stderr: Path, *, initialize: bool = False
    ) -> None:
        stderr.parent.mkdir(parents=True, exist_ok=True)
        with stderr.open("ab") as log:
            self.process = subprocess.Popen(
                [str(executable)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                start_new_session=True,
                bufsize=0,
            )
        self._sequence = 0
        self._poisoned = False
        try:
            self.progress = self.exchange("OPEN", root=str(root), plan=plan, initialize=initialize)
        except BaseException:
            self.abort()
            raise

    def exchange(self, operation: str, **fields: Any) -> dict[str, Any]:
        if self._poisoned or self.process.stdin is None or self.process.stdout is None:
            raise self._error("BACKTEST_NATIVE_OUTCOME_UNKNOWN")
        request = {"protocol": PROTOCOL, "sequence": self._sequence, "op": operation, **fields}
        payload = (
            json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        ).encode()
        if len(payload) > MAX_FRAME:
            self.abort()
            raise self._error("BACKTEST_NATIVE_FRAME_BOUND")
        source, target = self.process.stdin.fileno(), self.process.stdout.fileno()
        os.set_blocking(source, False)
        os.set_blocking(target, False)
        sent = 0
        received = bytearray()
        deadline = time.monotonic() + 30
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise self._error("BACKTEST_NATIVE_OUTCOME_UNKNOWN")
                readable, writable, _ = select.select([target], [source] if sent < len(payload) else [], [], remaining)
                if writable:
                    sent += os.write(source, payload[sent : sent + 65536])
                if readable:
                    chunk = os.read(target, 65536)
                    if not chunk:
                        raise self._error("BACKTEST_NATIVE_OUTCOME_UNKNOWN")
                    received.extend(chunk)
                    if len(received) > MAX_FRAME:
                        raise self._error("BACKTEST_NATIVE_FRAME_BOUND")
                    if b"\n" in received:
                        raw, tail = received.split(b"\n", 1)
                        response = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
                        if (
                            tail
                            or type(response) is not dict
                            or set(response) != {"protocol", "sequence", "payload"}
                            or response["protocol"] != PROTOCOL
                            or type(response["sequence"]) is not int
                            or response["sequence"] != self._sequence
                            or type(response["payload"]) is not dict
                            or sent != len(payload)
                        ):
                            raise self._error("BACKTEST_NATIVE_PROTOCOL_MISMATCH")
                        self._sequence += 1
                        result = response["payload"]
                        if set(result) == {"error"}:
                            if result["error"] != {"code": "BACKTEST_NATIVE_EXECUTION_REJECTED"}:
                                raise self._error("BACKTEST_NATIVE_PROTOCOL_MISMATCH")
                            raise OnlyBacktestError(
                                OnlyBacktestErrorPhase.EXECUTION,
                                "BACKTEST_NATIVE_EXECUTION_REJECTED",
                                "Native model rejected the step; the durable prefix is retained",
                            )
                        return result
        except (OSError, EOFError) as exc:
            self.abort()
            raise self._error("BACKTEST_NATIVE_OUTCOME_UNKNOWN") from exc
        except (ValueError, UnicodeError) as exc:
            self.abort()
            raise self._error("BACKTEST_NATIVE_PROTOCOL_MISMATCH") from exc
        except BaseException:
            self.abort()
            raise

    @staticmethod
    def _error(code: str) -> OnlyBacktestError:
        return OnlyBacktestError(
            OnlyBacktestErrorPhase.EXECUTION, code, "Native Backtest channel requires exact recovery"
        )

    def abort(self) -> None:
        self._poisoned = True
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.process.wait(timeout=10)
        for pipe in (self.process.stdin, self.process.stdout):
            if pipe is not None:
                pipe.close()

    def close(self) -> None:
        if not self._poisoned:
            try:
                self.exchange("CLOSE")
                self.process.wait(timeout=30)
            finally:
                self.abort()

    def __enter__(self) -> OnlyNativeBacktestProcess:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
