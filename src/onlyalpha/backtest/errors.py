"""Stable Backtest Product errors."""

from __future__ import annotations

from enum import StrEnum


class OnlyBacktestErrorPhase(StrEnum):
    COMMAND = "COMMAND"
    ADMISSION = "ADMISSION"
    OPERATIONAL = "OPERATIONAL"
    EXECUTION = "EXECUTION"
    EVIDENCE = "EVIDENCE"


class OnlyBacktestError(RuntimeError):
    def __init__(self, phase: OnlyBacktestErrorPhase, code: str, detail: str) -> None:
        self.phase = phase
        self.code = code
        self.detail = detail
        super().__init__(f"{phase.value}:{code}: {detail}")


class OnlyBacktestIntegrityError(OnlyBacktestError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(OnlyBacktestErrorPhase.OPERATIONAL, code, detail)


class OnlyBacktestNotFoundError(OnlyBacktestError):
    def __init__(self, run_id: str) -> None:
        super().__init__(OnlyBacktestErrorPhase.OPERATIONAL, "BACKTEST_RUN_NOT_FOUND", run_id)


class OnlyBacktestStateConflictError(OnlyBacktestError):
    def __init__(self, detail: str) -> None:
        super().__init__(OnlyBacktestErrorPhase.OPERATIONAL, "BACKTEST_RUN_STATE_CONFLICT", detail)


class OnlyBacktestStoreUnavailableError(OnlyBacktestError):
    def __init__(self, detail: str) -> None:
        super().__init__(OnlyBacktestErrorPhase.OPERATIONAL, "BACKTEST_STORE_UNAVAILABLE", detail)


__all__ = [name for name in globals() if name.startswith("Only")]
