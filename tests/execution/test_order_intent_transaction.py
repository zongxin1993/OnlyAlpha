from dataclasses import fields

from onlyalpha.execution.order_intent_fact import OnlyCommittedOrderIntentFact, OnlyOrderIntentFactDraft
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from onlyalpha.transaction.codec import (
    only_decode_committed_execution_transaction,
    only_encode_committed_execution_transaction,
)
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.transaction import OnlyPreparedRuntimeTransaction, OnlyRuntimePrecondition
from tests.integration_demo.environment import DAY_ONE, OnlyIntegrationEnvironment


def test_real_broker_order_intent_is_durable_projected_and_codec_restartable() -> None:
    environment = OnlyIntegrationEnvironment()
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")

    submitted = environment.submit_buy()
    assert submitted.order_id is not None
    records = environment.runtime.execution_transaction_query.records()
    intent = records[0]

    assert intent.operation_kind is OnlyRuntimeOperationKind.ORDER_INTENT
    assert intent.projection_ready
    assert intent.fact.order_id == submitted.order_id
    assert intent.fact.order.client_order_id == submitted.client_order_id
    assert intent.fact.reservation_identities
    assert only_decode_committed_execution_transaction(only_encode_committed_execution_transaction(intent)) == intent
    assert (
        environment.runtime.execution_transaction_query.transactions_for_order(intent.runtime_id, submitted.order_id)[0]
        == intent
    )


def test_same_order_request_does_not_create_a_second_intent_or_external_submit() -> None:
    environment = OnlyIntegrationEnvironment()
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")

    first = environment.submit_buy()
    second = environment.submit_buy()
    intents = tuple(
        item
        for item in environment.runtime.execution_transaction_query.records()
        if item.operation_kind is OnlyRuntimeOperationKind.ORDER_INTENT
    )

    assert second.order_id == first.order_id
    assert second.client_order_id == first.client_order_id
    assert len(intents) == 1
    assert environment.runtime.broker_gateway is not None
    assert len(environment.runtime.broker_gateway.query_orders(first.snapshot.account_id)) == 1


def test_order_intent_sqlite_roundtrip_and_reopen_preserve_authority(tmp_path) -> None:
    environment = OnlyIntegrationEnvironment()
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")
    environment.submit_buy()
    committed = environment.runtime.execution_transaction_query.records()[0]
    fact = committed.fact
    draft = OnlyOrderIntentFactDraft(
        **{item.name: getattr(fact, item.name) for item in fields(OnlyOrderIntentFactDraft)}
    )
    prepared = OnlyPreparedRuntimeTransaction(
        committed.transaction_id,
        committed.runtime_id,
        committed.operation_kind,
        committed.operation_identity,
        committed.account_id,
        committed.effective_time,
        fact.prepared_at,
        draft,
        committed.projections,
        committed.outbox_events,
        tuple(
            OnlyRuntimePrecondition(
                item.identity.component,
                item.identity.entity_key,
                item.identity.expected_version,
                item.identity.expected_state_hash,
            )
            for item in committed.projections
        ),
    )
    path = tmp_path / "order-intent.sqlite3"
    store = OnlySqliteRuntimePersistenceStore(path)
    inserted = store.commit(prepared, committed_at=committed.committed_at)
    assert inserted.inserted
    assert inserted.transaction.fact == committed.fact
    assert committed.projected_at is not None
    store.mark_projection_ready(
        committed.runtime_id,
        committed.execution_sequence,
        projected_at=committed.projected_at,
    )
    store.close()

    reopened = OnlySqliteRuntimePersistenceStore(path)
    restored = reopened.transactions_for_order(committed.runtime_id, fact.order_id)
    assert len(restored) == 1
    assert restored[0].fact == committed.fact
    assert restored[0].projection_ready
    reopened.close()


def test_order_intent_v1_without_execution_reference_remains_byte_semantically_compatible() -> None:
    environment = OnlyIntegrationEnvironment()
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")
    environment.submit_buy()
    fact = environment.runtime.execution_transaction_query.records()[0].fact
    payload = fact.to_dict()

    assert payload["schema_version"] == 1
    assert "execution_reference" not in payload
    assert OnlyCommittedOrderIntentFact.from_dict(payload).to_dict() == payload
