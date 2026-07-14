from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.results import OnlyOrderMutationResult


def test_snapshot_and_mutation_result_round_trip_losslessly(created_order) -> None:
    snapshot = created_order.snapshot
    assert OnlyOrderSnapshot.from_json(snapshot.to_json()) == snapshot
    assert OnlyOrderMutationResult.from_dict(created_order.to_dict()) == created_order


def test_same_inputs_produce_same_ids_snapshots_and_event_order(order_request) -> None:
    from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyEngineId, OnlyRuntimeId
    from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
    from onlyalpha.order.manager import OnlyOrderManager

    results = []
    for _ in range(100):
        runtime_id = OnlyRuntimeId("deterministic")
        manager = OnlyOrderManager(
            OnlyEngineId("engine"),
            runtime_id,
            OnlySequenceOrderIdGenerator(runtime_id),
            OnlySequenceClientOrderIdGenerator(runtime_id),
        )
        result = manager.create_order(
            order_request,
            OnlyClusterId("cluster"),
            OnlyAccountId("account"),
            OnlyTimestamp.from_unix_nanos(1),
        )
        submitted = manager.mark_submitted(result.order_id, OnlyTimestamp.from_unix_nanos(2))
        results.append(
            (
                result.order_id,
                submitted.snapshot,
                tuple(event.event_type for event in result.events + submitted.events),
            )
        )
    assert all(item == results[0] for item in results)
