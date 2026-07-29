from dataclasses import replace

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.execution.persistence_ports import OnlyExecutionTransactionOutboxKey
from onlyalpha.runtime.recovery.validation import OnlyOutboxAuthorityCheck, OnlyPostRecoveryCheckStatus
from tests.runtime.recovery.support.authority_fixture import OnlyPostRecoveryAuthorityFixture


class OnlyTestOutboxQuery:
    def __init__(self, rows, pending_count: int | None = None) -> None:  # type: ignore[no-untyped-def]
        self.rows = tuple(rows)
        self.count = sum(not item.published and item.projection_ready for item in self.rows)
        if pending_count is not None:
            self.count = pending_count

    def outbox_records(self, runtime_id):  # type: ignore[no-untyped-def]
        del runtime_id
        return self.rows

    def pending_count(self, runtime_id):  # type: ignore[no-untyped-def]
        del runtime_id
        return self.count


class OnlyTestTransactionQuery:
    def __init__(self, rows) -> None:  # type: ignore[no-untyped-def]
        self.rows = tuple(rows)

    def records(self, runtime_id, *, after_sequence: int = 0):  # type: ignore[no-untyped-def]
        del runtime_id
        return tuple(item for item in self.rows if item.execution_sequence > after_sequence)


def _failed(context) -> set[str]:  # type: ignore[no-untyped-def]
    return {
        item.code
        for item in OnlyOutboxAuthorityCheck().evaluate(context)
        if item.status is OnlyPostRecoveryCheckStatus.FAILED
    }


def test_normal_outbox_passes() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    assert not _failed(fixture.context())


def test_duplicate_event_id_and_durable_key_are_independent() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    rows = fixture.store.outbox_records(fixture.runtime_id)
    duplicate_event = (rows[0], replace(rows[1], event=rows[0].event))
    duplicate_key = (rows[0], replace(rows[1], key=rows[0].key))
    assert "POST_RECOVERY_DUPLICATE_OUTBOX_EVENT" in _failed(
        fixture.context(outbox_query=OnlyTestOutboxQuery(duplicate_event))
    )
    assert "POST_RECOVERY_DUPLICATE_OUTBOX_KEY" not in _failed(
        fixture.context(outbox_query=OnlyTestOutboxQuery(duplicate_event))
    )
    assert "POST_RECOVERY_DUPLICATE_OUTBOX_KEY" in _failed(
        fixture.context(outbox_query=OnlyTestOutboxQuery(duplicate_key))
    )


def test_outbox_runtime_scope_and_pending_count_are_validated() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    rows = fixture.store.outbox_records(fixture.runtime_id)
    wrong_key = OnlyExecutionTransactionOutboxKey(
        OnlyRuntimeId("wrong-runtime"), rows[0].key.execution_sequence, rows[0].key.event_sequence
    )
    wrong_rows = (replace(rows[0], key=wrong_key), *rows[1:])
    assert "POST_RECOVERY_OUTBOX_SCOPE_MISMATCH" in _failed(
        fixture.context(outbox_query=OnlyTestOutboxQuery(wrong_rows))
    )
    assert "POST_RECOVERY_OUTBOX_PENDING_COUNT_MISMATCH" in _failed(
        fixture.context(outbox_query=OnlyTestOutboxQuery(rows, pending_count=0))
    )


def test_outbox_rejects_orphan_and_unready_transaction_references() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    rows = fixture.store.outbox_records(fixture.runtime_id)
    orphan_key = OnlyExecutionTransactionOutboxKey(fixture.runtime_id, 2, rows[0].key.event_sequence)
    assert "POST_RECOVERY_OUTBOX_ORPHAN" in _failed(
        fixture.context(outbox_query=OnlyTestOutboxQuery((replace(rows[0], key=orphan_key),)))
    )
    transaction = fixture.store.records(fixture.runtime_id)[0]
    unready = replace(transaction, projection_ready=False, projected_at=None)
    assert "POST_RECOVERY_OUTBOX_REFERENCES_UNREADY_TRANSACTION" in _failed(
        fixture.context(transaction_query=OnlyTestTransactionQuery((unready,)))
    )


def test_continuation_outbox_must_exist_and_remain_unpublished() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    continuation = replace(
        fixture.outcome,
        continuation_start_sequence=1,
        continuation_end_sequence=1,
    )
    assert "POST_RECOVERY_CONTINUATION_OUTBOX_MISSING" in _failed(
        fixture.context(outcome=continuation, outbox_query=OnlyTestOutboxQuery(()))
    )
    rows = fixture.store.outbox_records(fixture.runtime_id)
    published = tuple(replace(item, published=True) for item in rows)
    assert "POST_RECOVERY_CONTINUATION_OUTBOX_PREMATURELY_PUBLISHED" in _failed(
        fixture.context(outcome=continuation, outbox_query=OnlyTestOutboxQuery(published))
    )
