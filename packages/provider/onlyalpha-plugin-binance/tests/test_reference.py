from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256

import pytest
from onlyalpha_market_binance_spot.capability import only_map_order_type, only_map_time_in_force
from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment
from onlyalpha_plugin_binance.errors import OnlyBinanceReferenceStoreError, OnlyBinanceSchemaError
from onlyalpha_plugin_binance.spot.reference.capture import OnlyBinanceSpotReferenceCapture
from onlyalpha_plugin_binance.spot.reference.store import OnlyBinanceSpotReferenceStore

from onlyalpha.plugin.api import OnlyTradingDay


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
    exchange_filters: list[dict[str, object]] | None = None,
) -> tuple[bytes, bytes]:
    data = {
        "timezone": "UTC",
        "serverTime": server_time,
        "rateLimits": [],
        "exchangeFilters": exchange_filters or [],
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


def _capture(
    *,
    captured_at: datetime = datetime(2026, 8, 28, 12, tzinfo=UTC),
    environment: OnlyBinanceEnvironment = OnlyBinanceEnvironment.LIVE,
    **changes: object,
) -> OnlyBinanceSpotReferenceCapture:
    exchange, execution = _payload(**changes)
    return OnlyBinanceSpotReferenceCapture.create(
        exchange,
        execution,
        captured_at,
        environment=environment,
        requested_symbols=("BTCUSDT", "ETHUSDT"),
    )


def test_semantic_identity_ignores_key_order_server_and_capture_time() -> None:
    one = _capture(server_time=1, reverse=False)
    exchange, execution = _payload(server_time=2, reverse=True)
    two = OnlyBinanceSpotReferenceCapture.create(exchange, execution, datetime(2026, 8, 29, tzinfo=UTC))
    assert one.authority.identity == two.authority.identity
    assert one.exchange_info_fingerprint != two.exchange_info_fingerprint
    assert one.capture_fingerprint != two.capture_fingerprint


def test_environment_changes_capture_but_not_semantic_identity() -> None:
    live = _capture(environment=OnlyBinanceEnvironment.LIVE)
    testnet = _capture(environment=OnlyBinanceEnvironment.SPOT_TESTNET)
    assert live.capture_fingerprint != testnet.capture_fingerprint
    assert live.authority.identity == testnet.authority.identity


@pytest.mark.parametrize("change", [{"tick": "0.02"}, {"step": "0.00002"}, {"status": "HALT"}])
def test_economic_change_creates_new_reference(change: dict[str, object]) -> None:
    assert _capture().authority.identity != _capture(**change).authority.identity


@pytest.mark.parametrize(
    "change",
    ("minimum_notional", "maximum_notional", "dynamic_multiplier", "permission", "capability"),
)
def test_each_relevant_semantic_change_updates_authority_identity(change: str) -> None:
    exchange, execution = _payload()
    exchange_object = json.loads(exchange)
    execution_object = json.loads(execution)
    symbol = exchange_object["symbols"][0]
    filters = {item["filterType"]: item for item in symbol["filters"]}
    if change == "minimum_notional":
        filters["NOTIONAL"]["minNotional"] = "6"
    elif change == "maximum_notional":
        filters["NOTIONAL"]["maxNotional"] = "8000000"
    elif change == "dynamic_multiplier":
        filters["PERCENT_PRICE"]["multiplierUp"] = "4"
    elif change == "permission":
        symbol["permissionSets"] = [["SPOT"], ["TRD_GRP_002"]]
    else:
        symbol["ocoAllowed"] = False
    changed = OnlyBinanceSpotReferenceCapture.create(
        json.dumps(exchange_object).encode(),
        json.dumps(execution_object).encode(),
        datetime(2026, 8, 28, 12, tzinfo=UTC),
    )
    assert changed.authority.identity != _capture().authority.identity


def test_market_lot_size_remains_distinct_from_limit_lot_size() -> None:
    reference = _capture().authority.references[0]
    assert reference.quantity_step == Decimal("0.00001")
    assert reference.market_quantity_step == Decimal("0")
    assert reference.maximum_quantity == Decimal("9000")
    assert reference.market_maximum_quantity == Decimal("100")


def test_conflicting_min_notional_and_notional_filters_fail_closed() -> None:
    exchange, execution = _payload()
    raw = json.loads(exchange)
    raw["symbols"][0]["filters"].append(
        {
            "filterType": "MIN_NOTIONAL",
            "minNotional": "6",
            "applyToMarket": True,
            "avgPriceMins": 5,
        }
    )
    with pytest.raises(OnlyBinanceSchemaError, match="BINANCE_NOTIONAL_FILTER_CONFLICT"):
        OnlyBinanceSpotReferenceCapture.create(
            json.dumps(raw).encode(), execution, datetime(2026, 8, 28, 12, tzinfo=UTC)
        )


def test_unknown_critical_filter_is_preserved_but_not_trade_eligible() -> None:
    reference = _capture(unknown=True).authority.references[0]
    assert reference.compatibility_status.value == "INCOMPATIBLE"
    assert not reference.market_product_eligible
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
    assert reference.venue_spot_supported
    assert not hasattr(reference, "account_eligible")


def test_store_reuse_and_corruption_fail_closed(tmp_path) -> None:
    store = OnlyBinanceSpotReferenceStore(tmp_path)
    capture = _capture()
    fingerprint = capture.authority.identity.authority_fingerprint
    first = store.publish(capture)
    second = store.publish(capture)
    assert first.capture_created and first.reference_created
    assert not second.capture_created and not second.reference_created
    assert first.compatibility_status == "COMPATIBLE"
    assert first.symbols == ("BTCUSDT", "ETHUSDT")
    assert first.semantic_reference_fingerprint == fingerprint
    assert store.load_capture_verified(capture.capture_fingerprint).authority.identity == capture.authority.identity
    assert store.load_reference_verified(fingerprint).identity == capture.authority.identity
    (tmp_path / "captures" / capture.capture_fingerprint / "exchangeInfo.json").write_bytes(b"{}")
    with pytest.raises(OnlyBinanceReferenceStoreError, match="RAW_CORRUPT"):
        store.load_capture_verified(capture.capture_fingerprint)


def test_multiple_captures_retain_one_semantic_revision(tmp_path) -> None:
    store = OnlyBinanceSpotReferenceStore(tmp_path)
    first = _capture(captured_at=datetime(2026, 8, 28, 10, tzinfo=UTC), server_time=1)
    second = _capture(captured_at=datetime(2026, 8, 28, 11, tzinfo=UTC), server_time=2, reverse=True)
    one = store.publish(first)
    two = store.publish(second)
    assert one.capture_created and one.reference_created
    assert two.capture_created and not two.reference_created
    assert one.capture_fingerprint != two.capture_fingerprint
    assert one.semantic_reference_fingerprint == two.semantic_reference_fingerprint
    assert (tmp_path / "captures" / one.capture_fingerprint).is_dir()
    assert (tmp_path / "captures" / two.capture_fingerprint).is_dir()
    assert len(tuple((tmp_path / "references").iterdir())) == 1


def test_semantic_corruption_and_parser_independent_replay(tmp_path, monkeypatch) -> None:
    store = OnlyBinanceSpotReferenceStore(tmp_path)
    capture = _capture()
    publication = store.publish(capture)

    def broken_normalizer(*args, **kwargs):
        raise AssertionError("semantic replay must not invoke the current normalizer")

    monkeypatch.setattr(
        "onlyalpha_plugin_binance.spot.reference.capture.only_normalize_binance_spot_reference",
        broken_normalizer,
    )
    assert (
        store.load_reference_verified(publication.semantic_reference_fingerprint).identity == capture.authority.identity
    )
    reference_path = tmp_path / "references" / publication.semantic_reference_fingerprint / "reference.json"
    reference_path.write_bytes(b"{}")
    with pytest.raises(OnlyBinanceReferenceStoreError, match="SEMANTIC_CORRUPT"):
        store.load_reference_verified(publication.semantic_reference_fingerprint)


def test_claimed_semantic_fingerprint_conflict_never_repairs_or_overwrites(tmp_path) -> None:
    store = OnlyBinanceSpotReferenceStore(tmp_path)
    capture = _capture()
    publication = store.publish(capture)
    target = tmp_path / "references" / publication.semantic_reference_fingerprint
    reference_path = target / "reference.json"
    manifest_path = target / "manifest.json"
    semantic = json.loads(reference_path.read_bytes())
    semantic["references"][0]["price_tick"] = "0.02"
    conflicting = (json.dumps(semantic, sort_keys=True, separators=(",", ":")) + "\n").encode()
    reference_path.write_bytes(conflicting)
    manifest = json.loads(manifest_path.read_bytes())
    manifest["semantic_sha256"] = sha256(conflicting).hexdigest()
    manifest_path.write_bytes((json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode())
    with pytest.raises(OnlyBinanceReferenceStoreError, match="REFERENCE_CORRUPT"):
        store.publish(capture)
    assert reference_path.read_bytes() == conflicting


def test_exchange_level_rules_are_authoritative_and_unknown_fails_closed() -> None:
    known = _capture(exchange_filters=[{"filterType": "EXCHANGE_MAX_NUM_ORDERS", "maxNumOrders": 1000}])
    changed = _capture(exchange_filters=[{"filterType": "EXCHANGE_MAX_NUM_ORDERS", "maxNumOrders": 1001}])
    unknown = _capture(exchange_filters=[{"filterType": "NEW_EXCHANGE_RULE", "value": 1}])
    assert known.authority.compatibility_status.value == "COMPATIBLE"
    assert known.authority.identity != changed.authority.identity
    assert unknown.authority.compatibility_status.value == "INCOMPATIBLE"
    with pytest.raises(ValueError, match="EXCHANGE_RULE_AUTHORITY_INCOMPATIBLE"):
        unknown.authority.resolve(
            unknown.authority.references[0].instrument_id,
            OnlyTradingDay(date(2026, 8, 29)),
        )


def test_capture_provenance_is_complete_and_does_not_enter_semantic_identity() -> None:
    capture = _capture(environment=OnlyBinanceEnvironment.SPOT_TESTNET)
    assert capture.provenance.provider == "BINANCE"
    assert capture.provenance.product == "SPOT"
    assert capture.provenance.environment is OnlyBinanceEnvironment.SPOT_TESTNET
    assert capture.provenance.parser_contract_version
    assert capture.provenance.requested_symbols == ("BTCUSDT", "ETHUSDT")
    assert {item.endpoint_id for item in capture.evidence} == {
        "/api/v3/exchangeInfo",
        "/api/v3/executionRules",
    }
    assert all(item.raw_sha256 == sha256(item.raw_bytes).hexdigest() for item in capture.evidence)
