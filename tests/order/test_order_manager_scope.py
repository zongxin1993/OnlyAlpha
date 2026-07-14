from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderRequestId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.manager import OnlyOrderManager


def test_indexes_and_open_orders_stay_consistent(order_manager: OnlyOrderManager, order_request, created_order) -> None:
    snapshot = created_order.snapshot
    assert order_manager.find_by_client_order_id(snapshot.client_order_id) == snapshot
    assert order_manager.list_by_cluster(OnlyClusterId("cluster-a")) == (snapshot,)
    assert order_manager.list_by_account(OnlyAccountId("account")) == (snapshot,)
    assert order_manager.list_by_instrument(order_request.instrument_id) == (snapshot,)
    assert order_manager.list_open_orders() == (snapshot,)


def test_request_id_deduplication_does_not_allocate_second_order(
    order_manager: OnlyOrderManager, order_request, created_order
) -> None:
    assert order_request.request_id == OnlyOrderRequestId("request-1")
    duplicate = order_manager.create_order(
        order_request,
        OnlyClusterId("cluster-a"),
        OnlyAccountId("account"),
        OnlyTimestamp.from_unix_nanos(2),
    )
    assert order_manager.snapshot_all() == (created_order.snapshot,)
    assert duplicate.order_id == created_order.order_id
