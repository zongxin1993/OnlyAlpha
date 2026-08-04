from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.operations.acceptance import (
    OnlyAcceptanceVerdict,
    OnlyPaperAcceptancePlan,
    OnlyPaperAcceptanceRunner,
)

pytestmark = pytest.mark.unit


def _plan() -> OnlyPaperAcceptancePlan:
    return OnlyPaperAcceptancePlan.load(Path("examples/acceptance/miniqmt_paper_v2.yaml"))


def test_frozen_live_profile_has_independent_collection_and_session_budgets() -> None:
    plan = _plan()

    assert OnlyPaperAcceptanceRunner._live_collection_timeout_seconds(plan) == 430  # noqa: SLF001
    assert OnlyPaperAcceptanceRunner._required_live_window_seconds(plan) == 505  # noqa: SLF001


def test_startup_timeout_is_not_the_live_collection_deadline() -> None:
    plan = _plan()

    assert plan.startup_timeout_seconds + plan.live_grace_seconds == 70
    assert OnlyPaperAcceptanceRunner._live_collection_timeout_seconds(plan) > 70  # noqa: SLF001


def test_pre_open_live_gate_does_not_assemble_or_connect_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = replace(_plan(), output_root=tmp_path / "acceptance")
    runner = OnlyPaperAcceptanceRunner(OnlyBacktestClock(datetime(2026, 8, 4, 1, 0, tzinfo=UTC)))

    def forbidden_engine_run(*args: object, **kwargs: object) -> tuple[object, ...]:
        del args, kwargs
        raise AssertionError("PRE_OPEN must not assemble or connect the real Engine")

    monkeypatch.setattr(OnlyPaperAcceptanceRunner, "_run_real_engine", forbidden_engine_run)

    result = runner.run(plan, "live-handoff")

    assert result.verdict is OnlyAcceptanceVerdict.NOT_EXECUTED
    assert result.cases["real_live_handoff"] is OnlyAcceptanceVerdict.NOT_EXECUTED
    assert result.evidences[0].reason_code == "MARKET_SESSION_NOT_OPEN"
