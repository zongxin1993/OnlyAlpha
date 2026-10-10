"""Cancellation must own its Run before the first source-frontier write."""

from __future__ import annotations

from dataclasses import replace

import psycopg
import pytest

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
    only_cancel_research_run_command_fingerprint,
)
from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority
from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
from onlyalpha.research.run.errors import OnlyResearchRunIntegrityError
from onlyalpha.research.run.model import OnlyResearchRunState
from tests.application.test_chart_calculation_admission import NOW
from tests.research.postgres.test_chart_calculation_compilation import compilation_system as compilation_system
from tests.research.postgres.test_chart_calculation_run_admission import handoff

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.parametrize("lock", ["row", "table_write_intent"])
def test_cancellation_locks_run_before_admission_writes_source_frontier(
    compilation_system, postgres_dsn, monkeypatch, lock
):
    fixture = compilation_system
    run = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    receipt = OnlyProductCommandReceipt(
        OnlyProductCommandId("00000000-0000-4000-8000-000000000931"),
        OnlyProductCommandKind.CANCEL_RESEARCH_RUN,
        only_cancel_research_run_command_fingerprint(run.run_id.value),
        OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, run.run_id.value),
        NOW,
    )
    original = OnlyPostgresProductCommandAuthority.insert_or_verify_admission.__func__
    witnessed = []

    def insert(cls, connection, admission):
        if admission.command_id == receipt.command_id:
            with psycopg.connect(postgres_dsn) as observer:
                # NOWAIT observes the actual held row lock, without time/sleep or
                # relying on a scheduler to arrange a deadlock.
                with pytest.raises(psycopg.errors.LockNotAvailable), observer.transaction():
                    if lock == "row":
                        observer.execute(
                            "SELECT run_id FROM public.research_run WHERE run_id=%s FOR UPDATE NOWAIT",
                            (run.run_id.value,),
                        )
                    else:
                        # T1 takes SHARE before its first frontier write. A mere
                        # Run FOR UPDATE holds ROW SHARE and is compatible with
                        # that SHARE. C would then upgrade after owning frontier:
                        # C(frontier)->O(SHARE), O(SHARE)->C(frontier).
                        observer.execute("LOCK TABLE public.research_run IN SHARE MODE NOWAIT")
                # The first admission write must not already hold the frontier.
                observer.execute(
                    "SELECT last_index FROM public.research_source_history_frontier WHERE singleton=TRUE FOR UPDATE NOWAIT"
                )
            witnessed.append(admission.command_id)
        return original(cls, connection, admission)

    monkeypatch.setattr(OnlyPostgresProductCommandAuthority, "insert_or_verify_admission", classmethod(insert))
    store = OnlyPostgresResearchRunStore(postgres_dsn)
    assert store.request_cancellation_with_receipt(run.run_id, receipt) == receipt
    assert witnessed == [receipt.command_id]
    cancelled = store.load(run.run_id)
    assert cancelled.state is OnlyResearchRunState.CANCELLED and cancelled.revision == 1
    assert store.request_cancellation_with_receipt(run.run_id, receipt) == receipt
    assert witnessed == [receipt.command_id]
    with pytest.raises(OnlyResearchRunIntegrityError, match="Product Command identity"):
        store.request_cancellation_with_receipt(run.run_id, replace(receipt, command_fingerprint="f" * 64))
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM public.research_run_attempt").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM public.product_command_receipt WHERE command_id=%s", (receipt.command_id.value,)
        ).fetchone() == (1,)
