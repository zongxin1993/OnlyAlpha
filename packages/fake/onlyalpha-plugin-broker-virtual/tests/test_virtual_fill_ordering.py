from dataclasses import replace
from datetime import date

from conftest import ACCOUNT, bar, order


def test_order_and_trade_queries_use_explicit_stable_keys(virtual_broker) -> None:
    clock, gateway, _ = virtual_broker
    first = bar(date(2026, 1, 5), 0)
    clock.advance_to(first.ts_event)
    gateway.on_bar(first)
    gateway.submit_order(replace(order(2), order_id=type(order(2).order_id)("z-order")))
    gateway.submit_order(replace(order(1), order_id=type(order(1).order_id)("a-order")))
    gateway.run_due()
    before = tuple((str(item.venue_order_id), str(item.order_id)) for item in gateway.query_orders(ACCOUNT))
    checkpoint = gateway.capture_checkpoint()
    gateway.restore_checkpoint(checkpoint)
    after = tuple((str(item.venue_order_id), str(item.order_id)) for item in gateway.query_orders(ACCOUNT))
    assert before == after == tuple(sorted(before))
