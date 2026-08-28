from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from onlyalpha_market_binance_spot.capability import only_map_order_type, only_map_time_in_force
from onlyalpha_plugin_binance.errors import OnlyBinanceReferenceStoreError
from onlyalpha_plugin_binance.spot.reference.capture import OnlyBinanceSpotReferenceCapture
from onlyalpha_plugin_binance.spot.reference.store import OnlyBinanceSpotReferenceStore


def _symbol(
    name: str,
    base: str,
    *,
    tick: str = "0.01",
    step: str = "0.00001",
    status: str = "TRADING",
    extra_filter: dict[str, object] | None = None,
) -> dict[str, object]:
    filters: list[dict[str, object]] = [
        {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1000000", "tickSize": tick},
        {"filterType": "LOT_SIZE", "minQty": step, "maxQty": "9000", "stepSize": step},
        {"filterType": "MARKET_LOT_SIZE", "minQty": "0", "maxQty": "100", "stepSize": "0"},
        {
            "filterType": "NOTIONAL",
            "minNotional": "5",
            "maxNotional": "9000000",
            "applyMinToMarket": True,
            "applyMaxToMarket": False,
            "avgPriceMins": 5,
        },
        {"filterType": "PERCENT_PRICE", "multiplierUp": "5", "multiplierDown": "0.2", "avgPriceMins": 5},
        {"filterType": "MAX_NUM_ORDERS", "maxNumOrders": 200},
        {"filterType": "MAX_NUM_ALGO_ORDERS", "maxNumAlgoOrders": 5},
        {"filterType": "MAX_NUM_ORDER_LISTS", "maxNumOrderLists": 20},
        {"filterType": "MAX_NUM_ORDER_AMENDS", "maxNumOrderAmends": 10},
        {
            "filterType": "TRAILING_DELTA",
            "minTrailingAboveDelta": 10,
            "maxTrailingAboveDelta": 2000,
            "minTrailingBelowDelta": 10,
            "maxTrailingBelowDelta": 2000,
        },
    ]
    if extra_filter:
        filters.append(extra_filter)
    return {
        "symbol": name,
        "status": status,
        "baseAsset": base,
        "quoteAsset": "USDT",
        "orderTypes": [
            "LIMIT",
            "MARKET",
            "STOP_LOSS",
            "STOP_LOSS_LIMIT",
            "TAKE_PROFIT",
            "TAKE_PROFIT_LIMIT",
            "LIMIT_MAKER",
        ],
        "icebergAllowed": True,
        "ocoAllowed": True,
        "otoAllowed": True,
        "opoAllowed": True,
        "quoteOrderQtyMarketAllowed": True,
        "allowTrailingStop": True,
        "cancelReplaceAllowed": True,
        "amendAllowed": True,
        "pegInstructionsAllowed": True,
        "isSpotTradingAllowed": True,
        "filters": filters,
        "permissionSets": [["SPOT", "MARGIN"]],
        "defaultSelfTradePreventionMode": "EXPIRE_MAKER",
        "allowedSelfTradePreventionModes": ["NONE", "EXPIRE_TAKER", "EXPIRE_MAKER", "EXPIRE_BOTH"],
    }


def _payload(
    *,
    tick: str = "0.01",
    step: str = "0.00001",
    status: str = "TRADING",
    server_time: int = 1,
    unknown: bool = False,
    reverse: bool = False,
) -> tuple[bytes, bytes]:
    data = {
        "timezone": "UTC",
        "serverTime": server_time,
        "rateLimits": [],
        "exchangeFilters": [],
        "symbols": [
            _symbol(
                "BTCUSDT",
                "BTC",
                tick=tick,
                step=step,
                status=status,
                extra_filter={"filterType": "NEW_CRITICAL", "x": "1"} if unknown else None,
            ),
            _symbol("ETHUSDT", "ETH", tick="0.01", step="0.0001"),
        ],
    }
    execution = {
        "symbolRules": [
            {
                "symbol": symbol,
                "rules": [
                    {
                        "ruleType": "PRICE_RANGE",
                        "bidLimitMultUp": "1.1",
                        "bidLimitMultDown": "0.9",
                        "askLimitMultUp": "1.1",
                        "askLimitMultDown": "0.9",
                    }
                ],
            }
            for symbol in ("BTCUSDT", "ETHUSDT")
        ]
    }
    return (json.dumps(data, sort_keys=reverse).encode(), json.dumps(execution, sort_keys=reverse).encode())


def _capture(**changes: object) -> OnlyBinanceSpotReferenceCapture:
    exchange, execution = _payload(**changes)
    return OnlyBinanceSpotReferenceCapture.create(exchange, execution, datetime(2026, 8, 28, 12, tzinfo=UTC))


def test_semantic_identity_ignores_key_order_server_and_capture_time() -> None:
    one = _capture(server_time=1, reverse=False)
    exchange, execution = _payload(server_time=2, reverse=True)
    two = OnlyBinanceSpotReferenceCapture.create(exchange, execution, datetime(2026, 8, 29, tzinfo=UTC))
    assert one.authority.identity == two.authority.identity
    assert one.exchange_info_fingerprint != two.exchange_info_fingerprint


@pytest.mark.parametrize("change", [{"tick": "0.02"}, {"step": "0.00002"}, {"status": "HALT"}])
def test_economic_change_creates_new_reference(change: dict[str, object]) -> None:
    assert _capture().authority.identity != _capture(**change).authority.identity


def test_unknown_critical_filter_is_preserved_but_not_trade_eligible() -> None:
    reference = _capture(unknown=True).authority.references[0]
    assert reference.compatibility_status.value == "INCOMPATIBLE"
    assert not reference.trade_eligible
    assert any(rule.category == "UNKNOWN_CRITICAL" for rule in reference.rules)


@pytest.mark.parametrize(
    ("native", "canonical", "instruction"),
    [
        ("LIMIT", "LIMIT", None),
        ("MARKET", "MARKET", None),
        ("STOP_LOSS", "STOP_MARKET", None),
        ("STOP_LOSS_LIMIT", "STOP_LIMIT", None),
        ("TAKE_PROFIT", "MARKET_IF_TOUCHED", None),
        ("TAKE_PROFIT_LIMIT", "LIMIT_IF_TOUCHED", None),
        ("LIMIT_MAKER", "LIMIT", "POST_ONLY"),
    ],
)
def test_order_capability_mapping(native: str, canonical: str, instruction: str | None) -> None:
    mapped, mapped_instruction = only_map_order_type(native)
    assert mapped.value == canonical
    assert (None if mapped_instruction is None else mapped_instruction.value) == instruction


def test_protocol_capabilities_preserve_group_stp_and_boolean_semantics() -> None:
    reference = _capture().authority.references[0]
    assert reference.time_in_force == tuple(only_map_time_in_force(item).value for item in ("GTC", "IOC", "FOK"))
    assert reference.order_group_capabilities == ("OCO", "OTO", "OPO")
    assert reference.default_stp_mode == "EXPIRE_MAKER"
    assert {name for name, supported in reference.capabilities if supported} == {
        "quoteOrderQtyMarketAllowed",
        "allowTrailingStop",
        "cancelReplaceAllowed",
        "amendAllowed",
        "pegInstructionsAllowed",
    }


def test_store_reuse_and_corruption_fail_closed(tmp_path) -> None:
    store = OnlyBinanceSpotReferenceStore(tmp_path)
    capture = _capture()
    fingerprint = capture.authority.identity.authority_fingerprint
    first = store.publish(capture)
    second = store.publish(capture)
    assert first.created and not second.created
    assert first.compatibility_status == "COMPATIBLE"
    assert first.symbols == ("BTCUSDT", "ETHUSDT")
    assert first.semantic_reference_fingerprint == fingerprint
    assert store.load_verified(fingerprint).authority.identity == capture.authority.identity
    (tmp_path / fingerprint / "exchangeInfo.json").write_bytes(b"{}")
    with pytest.raises(OnlyBinanceReferenceStoreError, match="RAW_CORRUPT"):
        store.load_verified(fingerprint)
