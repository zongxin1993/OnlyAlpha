#!/usr/bin/env python3
"""Provision a real Binance-derived A0 Product vertical.

Reference capture and historical provisioning are deliberately separate.  A
capture only proves market/account rules from its provider timestamp forward;
provisioning rejects an earlier interval instead of backdating that authority.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment
from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient
from onlyalpha_plugin_binance.common.private_http import (
    OnlyBinanceCredentials,
    OnlyBinancePrivateHttpClient,
)
from onlyalpha_plugin_binance.spot.data_source.normalize import only_normalize_rest_kline
from onlyalpha_plugin_binance.spot.reference.capture import OnlyBinanceSpotReferenceCapture
from onlyalpha_plugin_binance.usdm import (
    OnlyBinanceUsdmHistoricalNormalizer,
    OnlyBinanceUsdmReferenceCapture,
    only_normalize_binance_usdm_kline,
)
from onlyalpha_plugin_binance_spot import OnlyBinanceSpotMarketProductFactory, OnlyBinanceSpotReference
from onlyalpha_plugin_binance_spot.resource_provider import OnlyBinanceSpotBacktestResourceProvider
from onlyalpha_plugin_binance_usdm import OnlyBinanceUsdmMarketProductFactory, OnlyBinanceUsdmPublicMarketReference
from onlyalpha_plugin_binance_usdm.resource_provider import OnlyBinanceUsdmBacktestResourceProvider

from onlyalpha.application import OnlyCalculationEquivalenceCertificationApplicationService
from onlyalpha.backtest import (
    OnlyBacktestDeploymentCatalog,
    OnlyBacktestEconomicFactStore,
    OnlyBacktestMarketProductResourceRegistry,
)
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.definition import OnlyCalculationDataType, OnlyCalculationKind, OnlyCalculationTypeReference
from onlyalpha.calculation.equivalence import OnlyCalculationEquivalenceEvidenceV2Store
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataType
from onlyalpha.data.evidence import OnlyRawProviderObservation
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyFundingRateUpdate,
    OnlyMarketDataInboundUpdate,
    OnlyReferencePriceUpdate,
)
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyContractType,
    OnlyCurrencyType,
    OnlyMarketType,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyRawSymbol, OnlyRuntimeId
from onlyalpha.domain.instrument import OnlyCryptoPerpetual, OnlyCryptoSpot, OnlyInstrument
from onlyalpha.domain.market import (
    OnlyBar,
    OnlyBarSpecification,
    OnlyBarType,
    OnlyFundingRateFact,
    OnlyReferencePriceFact,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry, OnlyMarketProductResolutionContext
from onlyalpha.market_data.durable.ingress import OnlyMarketDataIngress
from onlyalpha.market_data.durable.models import OnlyMarketDataScope
from onlyalpha.market_data.durable.recovery import OnlyMarketDataRecoveryCoordinator
from onlyalpha.market_data.durable.revision import OnlyHistoricalMarketDataQueryService, OnlyRevisionCommitService
from onlyalpha.market_data.durable.wal import OnlyMarketDataWal
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.clickhouse import (
    OnlyClickHouseClient,
    OnlyClickHouseConfig,
    OnlyClickHouseMarketFactStore,
)
from onlyalpha.persistence.postgres import OnlyPostgresConfig, OnlyPostgresMarketDataCatalog
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.research.dataset import (
    OnlyDatasetEconomicBindingStore,
    OnlyEconomicFactManifest,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchDatasetDefinition,
    OnlyResearchDatasetEconomicBinding,
    OnlySealedMarketDataDatasetMaterializer,
    OnlySealedMarketDataMaterializationPlan,
)
from onlyalpha.research.definition.expression import (
    OnlyResearchComparison,
    OnlyResearchComparisonOperator,
    OnlyResearchDatasetFieldRef,
    OnlyResearchTypedLiteral,
    OnlyResearchVariableRef,
)
from onlyalpha.research.definition.model import (
    OnlyResearchCalculationInput,
    OnlyResearchCalculationInstance,
    OnlyResearchDatasetSelection,
    OnlyResearchDefinition,
    OnlyResearchFixedParameter,
    OnlyResearchSignals,
    OnlyResearchStatisticsRequest,
    OnlyResearchUniverseKind,
    OnlyResearchUniverseSelection,
)
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.evaluation.definition import OnlyResearchStatisticsDefinition, OnlyResearchStatisticsMethod
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives

_SPOT_URL = "https://api.binance.com"
_USDM_URL = "https://fapi.binance.com"
_RUNTIME = OnlyRuntimeId("a0-binance-golden-provisioner")
_BAR_SPEC = OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST)
_CAPTURE_SCHEMA = 1


def _dataset_event_range(start: datetime, end: datetime) -> OnlyTimeRange:
    """Include the closing event timestamp of the final requested 1m Bar."""
    return OnlyTimeRange(start, end + timedelta(microseconds=1))


def _capture_session_id(authority_fingerprint: str, segment_id: str) -> str:
    """Keep each physical capture session unique while retaining its authority provenance."""
    return f"{authority_fingerprint}:{segment_id}"


def _ensure_product_roots(layout: OnlyUserDataLayout) -> None:
    for path in (layout.research_artifact_root, layout.backtest_evidence_root):
        path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class _Page:
    endpoint: str
    parameters: tuple[tuple[str, str], ...]
    payload: bytes
    rows: tuple[Any, ...]
    received_ns: int


def _json_bytes(value: object) -> bytes:
    return only_canonical_json(value).encode("utf-8")


def _decode(payload: bytes, *, expected: type[list[Any]] | type[dict[str, Any]]) -> Any:
    value = json.loads(payload)
    if not isinstance(value, expected):
        raise ValueError("BINANCE_RESPONSE_SHAPE_INVALID")
    return value


def _server_time(client: OnlyBinancePublicHttpClient, path: str) -> int:
    value = _decode(client.get_json(path), expected=dict)
    server_time = value.get("serverTime")
    if isinstance(server_time, bool) or not isinstance(server_time, int) or server_time <= 0:
        raise ValueError("BINANCE_SERVER_TIME_INVALID")
    return server_time


def _write_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (only_canonical_json(payload) + "\n").encode("utf-8")
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise ValueError(f"IMMUTABLE_OPERATOR_OUTPUT_CONFLICT:{path}") from None


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _unb64(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("REFERENCE_CAPTURE_CORRUPT")
    return base64.b64decode(value, validate=True)


def capture_reference(path: Path, *, products: tuple[str, ...]) -> dict[str, object]:
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != _CAPTURE_SCHEMA:
            raise ValueError("REFERENCE_CAPTURE_CORRUPT")
        return raw
    result: dict[str, object] = {"schema_version": _CAPTURE_SCHEMA}
    if "spot" in products:
        public = OnlyBinancePublicHttpClient(_SPOT_URL, max_response_bytes=16 * 1024 * 1024)
        server_ms = _server_time(public, "/api/v3/time")
        captured = datetime.fromtimestamp(server_ms / 1000, tz=UTC)
        symbols = ("BTCUSDT", "ETHUSDT")
        symbol_json = json.dumps(symbols, separators=(",", ":"))
        exchange = public.get_json("/api/v3/exchangeInfo", {"symbols": symbol_json})
        execution = public.get_json("/api/v3/executionRules", {"symbols": symbol_json})
        spot_reference_capture = OnlyBinanceSpotReferenceCapture.create(
            exchange,
            execution,
            captured,
            environment=OnlyBinanceEnvironment.LIVE,
            requested_symbols=symbols,
        )
        result["spot"] = {
            "captured_at": spot_reference_capture.captured_at.isoformat(),
            "server_time_ms": server_ms,
            "capture_fingerprint": spot_reference_capture.capture_fingerprint,
            "exchange_info": _b64(exchange),
            "execution_rules": _b64(execution),
        }
    if "usdm" in products:
        public = OnlyBinancePublicHttpClient(_USDM_URL, max_response_bytes=16 * 1024 * 1024)
        server_ms = _server_time(public, "/fapi/v1/time")
        captured = datetime.fromtimestamp(server_ms / 1000, tz=UTC)
        api_key = os.environ.get("ONLYALPHA_BINANCE_API_KEY")
        secret = os.environ.get("ONLYALPHA_BINANCE_API_SECRET")
        if not api_key or not secret:
            raise ValueError("BINANCE_LIVE_READONLY_CREDENTIALS_REQUIRED")
        private = OnlyBinancePrivateHttpClient(
            _USDM_URL,
            OnlyBinanceCredentials(api_key, secret),
            lambda: _server_time(public, "/fapi/v1/time"),
        )
        exchange = public.get_json("/fapi/v1/exchangeInfo")
        funding = public.get_json("/fapi/v1/fundingInfo")
        brackets = private.request_json("GET", "/fapi/v1/leverageBracket", {"symbol": "BTCUSDT"})
        position_mode = private.request_json("GET", "/fapi/v1/positionSide/dual")
        positions = private.request_json("GET", "/fapi/v3/positionRisk", {"symbol": "BTCUSDT"})
        mode_value = _decode(position_mode, expected=dict).get("dualSidePosition")
        if not isinstance(mode_value, bool):
            raise ValueError("BINANCE_USDM_POSITION_MODE_INVALID")
        position_rows = _decode(positions, expected=list)
        selected = [item for item in position_rows if isinstance(item, dict) and item.get("symbol") == "BTCUSDT"]
        if not selected:
            raise ValueError("BINANCE_USDM_POSITION_PROFILE_MISSING")
        leverages = {str(item.get("leverage")) for item in selected}
        margins = {
            "ISOLATED" if item.get("marginType") == "isolated" or item.get("isolated") is True else "CROSS"
            for item in selected
        }
        if len(leverages) != 1 or len(margins) != 1:
            raise ValueError("BINANCE_USDM_ACCOUNT_PROFILE_AMBIGUOUS")
        account_profile = _json_bytes(
            {
                "positionMode": "HEDGE" if mode_value else "NETTING",
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "marginMode": next(iter(margins)),
                        "leverage": next(iter(leverages)),
                    }
                ],
            }
        )
        usdm_reference_capture = OnlyBinanceUsdmReferenceCapture.create(
            exchange,
            funding,
            brackets,
            account_profile,
            captured_at=captured,
            coverage_start=captured,
        )
        result["usdm"] = {
            "captured_at": usdm_reference_capture.captured_at.isoformat(),
            "server_time_ms": server_ms,
            "capture_fingerprint": usdm_reference_capture.capture_fingerprint,
            "exchange_info": _b64(exchange),
            "funding_info": _b64(funding),
            "leverage_brackets": _b64(brackets),
            "position_mode_response": _b64(position_mode),
            "position_risk_response": _b64(positions),
            "account_profile": _b64(account_profile),
        }
    _write_exclusive(path, result)
    return result


def _capture_authorities(
    raw: Mapping[str, object],
) -> tuple[OnlyBinanceSpotReferenceCapture | None, OnlyBinanceUsdmReferenceCapture | None]:
    spot = None
    if isinstance(raw.get("spot"), dict):
        spot_value = cast(dict[str, object], raw["spot"])
        spot = OnlyBinanceSpotReferenceCapture.create(
            _unb64(spot_value["exchange_info"]),
            _unb64(spot_value["execution_rules"]),
            datetime.fromisoformat(str(spot_value["captured_at"])),
            environment=OnlyBinanceEnvironment.LIVE,
            requested_symbols=("BTCUSDT", "ETHUSDT"),
        )
        if spot.capture_fingerprint != spot_value["capture_fingerprint"]:
            raise ValueError("BINANCE_SPOT_CAPTURE_FINGERPRINT_CONFLICT")
    usdm = None
    if isinstance(raw.get("usdm"), dict):
        usdm_value = cast(dict[str, object], raw["usdm"])
        captured = datetime.fromisoformat(str(usdm_value["captured_at"]))
        usdm = OnlyBinanceUsdmReferenceCapture.create(
            _unb64(usdm_value["exchange_info"]),
            _unb64(usdm_value["funding_info"]),
            _unb64(usdm_value["leverage_brackets"]),
            _unb64(usdm_value["account_profile"]),
            captured_at=captured,
            coverage_start=captured,
        )
        if usdm.capture_fingerprint != usdm_value["capture_fingerprint"]:
            raise ValueError("BINANCE_USDM_CAPTURE_FINGERPRINT_CONFLICT")
    return spot, usdm


def _pages(
    client: OnlyBinancePublicHttpClient,
    endpoint: str,
    parameters: Mapping[str, str],
    *,
    start_ms: int,
    end_ms: int,
    timestamp_field: int | str,
    page_size: int,
) -> tuple[_Page, ...]:
    cursor = start_ms
    pages: list[_Page] = []
    while cursor < end_ms:
        query = dict(parameters)
        query.update({"startTime": str(cursor), "endTime": str(end_ms - 1), "limit": str(page_size)})
        received = time.time_ns()
        payload = client.get_json(endpoint, query)
        rows = _decode(payload, expected=list)
        if not rows:
            break
        timestamps: list[int] = []
        for row in rows:
            value = (
                row[timestamp_field]
                if isinstance(timestamp_field, int) and isinstance(row, list)
                else row.get(timestamp_field)
                if isinstance(timestamp_field, str) and isinstance(row, dict)
                else None
            )
            if isinstance(value, bool):
                raise ValueError("BINANCE_HISTORY_TIMESTAMP_INVALID")
            timestamps.append(int(str(value)))
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            raise ValueError("BINANCE_HISTORY_PAGE_ORDER_INVALID")
        pages.append(_Page(endpoint, tuple(sorted(query.items())), payload, tuple(rows), received))
        next_cursor = timestamps[-1] + (60_000 if isinstance(timestamp_field, int) else 1)
        if next_cursor <= cursor:
            raise ValueError("BINANCE_HISTORY_PAGINATION_NO_PROGRESS")
        cursor = next_cursor
        if len(rows) < page_size:
            break
    return tuple(pages)


def _precision(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("DECIMAL_PRECISION_INVALID")
    return max(-exponent, 0)


def _spot_instrument(reference: OnlyBinanceSpotReference) -> OnlyCryptoSpot:
    return OnlyCryptoSpot(
        instrument_id=reference.instrument_id,
        raw_symbol=OnlyRawSymbol(reference.raw_symbol),
        market_type=OnlyMarketType.CASH,
        quote_currency=OnlyCurrency(reference.quote_currency, 8, OnlyCurrencyType.CRYPTO),
        settlement_currency=OnlyCurrency(reference.quote_currency, 8, OnlyCurrencyType.CRYPTO),
        base_currency=OnlyCurrency(reference.base_currency, 8, OnlyCurrencyType.CRYPTO),
        price_precision=_precision(reference.price_tick),
        quantity_precision=_precision(reference.quantity_step),
        tick_size=OnlyPrice(reference.price_tick, _precision(reference.price_tick)),
        step_size=OnlyQuantity(reference.quantity_step, _precision(reference.quantity_step)),
        minimum_quantity=OnlyQuantity(reference.minimum_quantity, _precision(reference.quantity_step)),
        maximum_quantity=None
        if reference.maximum_quantity is None
        else OnlyQuantity(reference.maximum_quantity, _precision(reference.quantity_step)),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        trading_calendar_id=OnlyCalendarId("BINANCE-24X7"),
    )


def _usdm_instrument(reference: OnlyBinanceUsdmPublicMarketReference) -> OnlyCryptoPerpetual:
    base = reference.raw_symbol.removesuffix("USDT")
    price_precision = _precision(reference.price_tick)
    quantity_precision = _precision(reference.quantity_step)
    currency = OnlyCurrency(reference.settlement_currency, 8, OnlyCurrencyType.CRYPTO)
    return OnlyCryptoPerpetual(
        instrument_id=reference.instrument_id,
        raw_symbol=OnlyRawSymbol(reference.raw_symbol),
        market_type=OnlyMarketType.DERIVATIVE,
        quote_currency=currency,
        settlement_currency=currency,
        margin_currency=currency,
        base_currency=OnlyCurrency(base, 8, OnlyCurrencyType.CRYPTO),
        price_precision=price_precision,
        quantity_precision=quantity_precision,
        tick_size=OnlyPrice(reference.price_tick, price_precision),
        step_size=OnlyQuantity(reference.quantity_step, quantity_precision),
        minimum_quantity=OnlyQuantity(reference.minimum_quantity, quantity_precision),
        maximum_quantity=None
        if reference.maximum_quantity is None
        else OnlyQuantity(reference.maximum_quantity, quantity_precision),
        contract_multiplier=OnlyMultiplier(reference.contract_multiplier, 0),
        contract_type=OnlyContractType.LINEAR,
        trading_calendar_id=OnlyCalendarId("BINANCE-24X7"),
    )


def _bar_update(bar: OnlyBar, source: OnlyMarketDataSourceId, version: OnlyDataVersion) -> OnlyMarketDataInboundUpdate:
    sequence = int(bar.bar_start.timestamp()) // 60
    return OnlyMarketDataInboundUpdate(
        only_bar_update_id(source, bar.instrument_id, bar.bar_type, bar.bar_start, version),
        _RUNTIME,
        source,
        OnlyDataSequence(sequence),
        version,
        bar.instrument_id,
        OnlyMarketDataType.BAR,
        OnlyBarUpdate(bar),
        OnlyTimestamp.from_datetime(bar.ts_event),
        OnlyTimestamp.from_datetime(bar.ts_init),
        sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
    )


def _fact_update(
    fact: OnlyFundingRateFact | OnlyReferencePriceFact,
    source: OnlyMarketDataSourceId,
    version: OnlyDataVersion,
) -> OnlyMarketDataInboundUpdate:
    payload: OnlyFundingRateUpdate | OnlyReferencePriceUpdate
    if isinstance(fact, OnlyFundingRateFact):
        timestamp = fact.funding_time
        data_type = OnlyMarketDataType.FUNDING_RATE
        payload = OnlyFundingRateUpdate(fact)
    else:
        timestamp = fact.ts_event
        data_type = OnlyMarketDataType.REFERENCE_PRICE
        payload = OnlyReferencePriceUpdate(fact)
    return OnlyMarketDataInboundUpdate(
        OnlyMarketDataUpdateId(fact.fact_id),
        _RUNTIME,
        source,
        OnlyDataSequence(int(timestamp.timestamp() * 1000)),
        version,
        fact.instrument_id,
        data_type,
        payload,
        OnlyTimestamp.from_datetime(timestamp),
        OnlyTimestamp.from_datetime(timestamp),
        sequence_semantics=OnlyDataSequenceSemantics.MONOTONIC,
    )


def _observation(
    page: _Page,
    *,
    source: str,
    capture_session: str,
    market: str,
    stream: str,
    ordinal: int,
) -> OnlyRawProviderObservation:
    return OnlyRawProviderObservation(
        source_id=source,
        capture_session_id=capture_session,
        provider="BINANCE",
        venue="BINANCE",
        market=market,
        stream=stream,
        provider_event_type="REST_PAGE",
        provider_event_id=only_canonical_fingerprint({"endpoint": page.endpoint, "parameters": page.parameters}),
        provider_sequence=ordinal,
        ts_receive_ns=page.received_ns,
        payload=page.payload,
        provider_schema="BINANCE_REST_JSON@1",
        provenance="REST_BACKFILL",
    )


def _persist_bars(
    *,
    pages: tuple[_Page, ...],
    page_updates: tuple[tuple[OnlyMarketDataInboundUpdate, ...], ...],
    instrument: OnlyInstrument,
    source: OnlyMarketDataSourceId,
    version: OnlyDataVersion,
    market: str,
    capture_session: str,
    start: datetime,
    end: datetime,
    wal_root: Path,
    store: OnlyClickHouseMarketFactStore,
    catalog: OnlyPostgresMarketDataCatalog,
) -> tuple[str, OnlyMarketDataScope]:
    wal = OnlyMarketDataWal(wal_root, capacity_bytes=512 * 1024 * 1024)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id=f"onlyalpha-plugin-binance-{market.lower()}",
        normalizer_version="1",
        ingest_clock_ns=time.time_ns,
    )
    segment_id = ingress.begin_segment()
    physical_capture_session = _capture_session_id(capture_session, segment_id)
    for ordinal, (page, updates) in enumerate(zip(pages, page_updates, strict=True), start=1):
        ingress.record(
            _observation(
                page,
                source=str(source),
                capture_session=physical_capture_session,
                market=market,
                stream="1m-klines",
                ordinal=ordinal,
            ),
            updates,
        )
    if not pages:
        raise ValueError("BINANCE_BAR_HISTORY_EMPTY")
    ingress.seal()
    bar_type = OnlyBarType(instrument.instrument_id, _BAR_SPEC, OnlyAggregationSource.EXTERNAL)
    scope = OnlyMarketDataScope(
        str(source),
        market,
        str(instrument.instrument_id),
        "BAR",
        int(start.timestamp() * 1_000_000_000),
        int(end.timestamp() * 1_000_000_000),
        str(version),
        only_canonical_fingerprint(bar_type.to_dict()),
    )
    coordinator = OnlyMarketDataRecoveryCoordinator(
        wal,
        store,
        catalog,
        OnlyRevisionCommitService(store, catalog),
    )
    if coordinator.drain(segment_id, scope) not in {"COMMITTED", "ALREADY_COMMITTED"}:
        raise ValueError("BINANCE_BAR_REVISION_INCOMPLETE")
    return catalog.latest_sealed_revision(scope).revision_id, scope


def _persist_raw_pages(
    pages: tuple[_Page, ...],
    *,
    source: str,
    capture_session: str,
    market: str,
    stream: str,
    wal_root: Path,
    store: OnlyClickHouseMarketFactStore,
    catalog: OnlyPostgresMarketDataCatalog,
) -> None:
    if not pages:
        raise ValueError(f"BINANCE_{stream.upper()}_HISTORY_EMPTY")
    wal = OnlyMarketDataWal(wal_root, capacity_bytes=128 * 1024 * 1024)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="raw-only", normalizer_version="1", ingest_clock_ns=time.time_ns)
    segment_id = ingress.begin_segment()
    physical_capture_session = _capture_session_id(capture_session, segment_id)
    for ordinal, page in enumerate(pages, start=1):
        ingress.record(
            _observation(
                page,
                source=source,
                capture_session=physical_capture_session,
                market=market,
                stream=stream,
                ordinal=ordinal,
            ),
            None,
        )
    segment = ingress.seal()
    records = wal.read_sealed(segment_id)
    store.write_segment(segment, records)
    store.verify_segment(segment, records)
    catalog.commit_durable_segments((segment,))
    wal.mark_gc_eligible(segment_id)
    wal.collect_garbage(segment_id)


def _definition(dataset: OnlyResearchDatasetDefinition) -> dict[str, object]:
    def reference(kind: OnlyCalculationKind, type_id: str) -> OnlyCalculationTypeReference:
        return OnlyCalculationTypeReference(kind, type_id, "1")

    calculations = (
        OnlyResearchCalculationInstance(
            "returns_short",
            reference(OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.rolling_return"),
            {"period": OnlyResearchFixedParameter(2)},
            ("value",),
        ),
        OnlyResearchCalculationInstance(
            "returns_long",
            reference(OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.rolling_return"),
            {"period": OnlyResearchFixedParameter(5)},
            ("value",),
        ),
        OnlyResearchCalculationInstance(
            "momentum",
            reference(OnlyCalculationKind.FACTOR, "onlyalpha.factor.momentum"),
            {
                "short_weight": OnlyResearchFixedParameter(Decimal("1")),
                "long_weight": OnlyResearchFixedParameter(Decimal("1")),
            },
            ("factor_value",),
            (
                OnlyResearchCalculationInput("return_short", OnlyResearchVariableRef("returns_short", "value")),
                OnlyResearchCalculationInput("return_long", OnlyResearchVariableRef("returns_long", "value")),
            ),
        ),
    )
    zero = OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("0"))
    target = OnlyResearchCalculationInstance(
        "forward_return_1",
        reference(OnlyCalculationKind.TARGET, "onlyalpha.target.forward_return"),
        {"exit_offset": OnlyResearchFixedParameter(1)},
        ("target_value",),
        (
            OnlyResearchCalculationInput("entry_price", "bar.close"),
            OnlyResearchCalculationInput("exit_price", "bar.close"),
        ),
    )
    definition = OnlyResearchDefinition(
        OnlyResearchDatasetSelection(
            OnlyResearchUniverseSelection(
                OnlyResearchUniverseKind.SINGLE_INSTRUMENT
                if len(dataset.instruments) == 1
                else OnlyResearchUniverseKind.EXPLICIT_INSTRUMENT_SET,
                tuple(str(item) for item in dataset.instruments),
            ),
            dataset.bar_specification,
            dataset.aggregation_source,
            dataset.time_range.start.isoformat(),
            dataset.time_range.end.isoformat(),
            dataset.adjustment_type,
            dataset.adjustment_reference,
        ),
        calculations,
        OnlyResearchComparison(
            OnlyResearchComparisonOperator.GT,
            OnlyResearchDatasetFieldRef("close"),
            zero,
        ),
        OnlyResearchSignals(
            OnlyResearchComparison(
                OnlyResearchComparisonOperator.GT,
                OnlyResearchVariableRef("momentum", "factor_value"),
                zero,
            ),
            OnlyResearchComparison(
                OnlyResearchComparisonOperator.LE,
                OnlyResearchVariableRef("momentum", "factor_value"),
                zero,
            ),
        ),
        (target,),
        (
            OnlyResearchStatisticsRequest(
                OnlyResearchVariableRef("momentum", "factor_value"),
                "forward_return_1",
                OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC),
            ),
        ),
        display_metadata={"name": "A0 Binance real-history momentum"},
    )
    return dict(definition.to_dict())


def _calendar() -> dict[str, object]:
    return {
        "calendar_id": "BINANCE-24X7",
        "venue": "BINANCE",
        "timezone": "UTC",
        "sessions": [
            {
                "name": "continuous",
                "opens_at": "00:00:00",
                "closes_at": "23:59:59",
                "session_type": "CONTINUOUS",
            }
        ],
        "holidays": [],
        "weekend_days": [],
    }


def _instrument_document(instrument: OnlyInstrument, *, asset_class: str) -> dict[str, object]:
    if instrument.base_currency is None:
        raise ValueError("BINANCE_INSTRUMENT_BASE_CURRENCY_REQUIRED")
    result: dict[str, object] = {
        "instrument_id": str(instrument.instrument_id),
        "asset_class": asset_class,
        "timezone": "UTC",
        "trading_calendar_id": "BINANCE-24X7",
        "price_precision": instrument.price_precision,
        "quantity_precision": instrument.quantity_precision,
        "price_increment": str(instrument.tick_size.value),
        "quantity_increment": str(instrument.step_size.value),
        "lot_size": str(instrument.step_size.value),
        "minimum_quantity": str((instrument.minimum_quantity or instrument.step_size).value),
        "maximum_quantity": str(
            (instrument.maximum_quantity or OnlyQuantity(Decimal("100000000"), instrument.quantity_precision)).value
        ),
        "contract_multiplier": str(instrument.contract_multiplier.value),
    }
    if asset_class == "CRYPTO_SPOT":
        result.update(
            base_currency=instrument.base_currency.code,
            minimum_notional="0",
        )
    else:
        if instrument.margin_currency is None:
            raise ValueError("BINANCE_INSTRUMENT_MARGIN_CURRENCY_REQUIRED")
        result.update(
            base_currency=instrument.base_currency.code,
            margin_currency=instrument.margin_currency.code,
            contract_type="LINEAR",
        )
    return result


def _product_document(
    *,
    product: str,
    instruments: tuple[OnlyInstrument, ...],
    start: datetime,
    end: datetime,
    market_config: Mapping[str, object],
) -> OnlyClusterRunConfig:
    universe = f"a0-{product}"
    base_currency = "USDT"
    payload = {
        "schema_version": "1.0",
        "market": market_config,
        "cluster": {
            "cluster_id": universe,
            "account_id": "backtest-account",
            "enabled": True,
            "runtime_type": "BACKTEST",
            "risk_profile_id": "default-risk",
        },
        "runtime": {
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "base_currency": base_currency,
            "extensions": {"replay": {"stop_on_data_error": True}},
        },
        "reference_data": {
            "calendars": [_calendar()],
            "instruments": [
                _instrument_document(
                    item,
                    asset_class="CRYPTO_SPOT" if isinstance(item, OnlyCryptoSpot) else "CRYPTO_PERPETUAL",
                )
                for item in instruments
            ],
        },
        "universes": [
            {
                "universe_id": universe,
                "type": "STATIC",
                "instruments": [str(item.instrument_id) for item in instruments],
            }
        ],
        "data_sources": [
            {
                "source_id": "operator-placeholder",
                "plugin": "onlyalpha-dataset-snapshot",
                "data_version": "operator-placeholder-v1",
                "batch_size": 1024,
                "coverage": {"universe_ids": [universe]},
                "extensions": {},
            }
        ],
        "accounts": [
            {
                "account_id": "backtest-account",
                "gateway_id": "virtual-main",
                "broker_fee_contract": {
                    "contract_id": "VIRTUAL_SIMULATION_ZERO_BROKER_FEES",
                    "contract_version": "1",
                },
                "fee_reconciliation_policy": {
                    "policy_id": "STANDARD_FEE_RECONCILIATION",
                    "policy_version": "1",
                },
                "initial_cash": {"value": "100000.00", "currency": base_currency},
            }
        ],
        "brokers": [
            {
                "gateway_id": "virtual-main",
                "plugin": "virtual",
                "extensions": {"matching": {"type": "NEXT_BAR"}, "slippage": {"type": "NONE"}},
            }
        ],
        "strategy": {"fingerprint": "a" * 64},
        "factors": [],
        "output": {"formats": ["JSON"]},
    }
    return OnlyClusterRunConfig.from_mapping(payload, source_path=f"<a0-{product}-provisioner>")


def _resource_document(provider_id: str, resource_id: str, payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider_id": provider_id,
        "resource_id": resource_id,
        "payload": payload,
    }


def _backtest_request(binding: str, configuration: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "strategy_fingerprint": "0" * 64,
        "dataset_binding_fingerprint": binding,
        "market_product_configuration_fingerprint": configuration,
        "portfolio_profile": {"profile_id": "fixed-capital", "version": "1"},
        "risk_profile": {"profile_id": "default-risk", "version": "1"},
        "execution_profile": {"profile_id": "virtual-next-bar", "version": "1"},
        "initial_account": {"base_currency": "USDT", "capital": "100000.00"},
        "runtime_options": {"ordered_fact_policy": "ORDERED_FACTS_V1"},
    }


def _certify_strategy_calculations(
    definition_document: Mapping[str, object],
    dataset_store: OnlyParquetResearchDatasetSnapshotStore,
    semantic_root: Path,
) -> tuple[str, ...]:
    calculations = OnlyCalculationRegistry()
    only_discover_plugins(
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        OnlyBrokerFeeContractRegistry(),
        OnlyMarketProductFactoryRegistry(),
        calculations,
        fail_fast=True,
    )
    only_register_research_predicate_primitives(calculations)
    only_register_trading_predicate_primitives(calculations)
    resolved = OnlyResearchDefinitionResolver(calculations, dataset_store).resolve(
        OnlyResearchDefinition.from_dict(definition_document)
    )
    candidates = tuple(
        item
        for item in resolved.specification_resolution.candidates
        if item.calculation_id == "decision" and item.candidate_fingerprint is not None
    )
    nodes = {node.fingerprint: node for candidate in candidates for node in candidate.graph.nodes}
    authority = OnlyCalculationEquivalenceCertificationApplicationService(
        calculations,
        OnlyCalculationEquivalenceEvidenceV2Store(semantic_root),
    )
    return tuple(authority.certify(nodes[fingerprint]).evidence_fingerprint for fingerprint in sorted(nodes))


def _publish_vertical(
    *,
    name: str,
    instruments: tuple[OnlyInstrument, ...],
    revision_ids: tuple[str, ...],
    scopes: tuple[OnlyMarketDataScope, ...],
    composition_fingerprint: str,
    config: OnlyClusterRunConfig,
    definition: OnlyResearchDatasetDefinition,
    economic_updates: tuple[OnlyMarketDataInboundUpdate, ...],
    layout: OnlyUserDataLayout,
    query: OnlyHistoricalMarketDataQueryService,
    output: Path,
) -> dict[str, object]:
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    snapshot = OnlySealedMarketDataDatasetMaterializer(
        query,
        dataset_store,
        dataset_store,
        lambda: datetime.now(UTC),
    ).materialize(OnlySealedMarketDataMaterializationPlan(revision_ids, definition, scopes))
    manifests: list[OnlyEconomicFactManifest] = []
    for family, kind in (
        (OnlyMarketDataType.REFERENCE_PRICE, OnlyReferencePriceKind.MARK),
        (OnlyMarketDataType.FUNDING_RATE, None),
    ):
        selected = tuple(
            item
            for item in economic_updates
            if item.data_type is family
            and (kind is None or getattr(getattr(item.payload, "fact", None), "kind", None) is kind)
        )
        if selected:
            manifests.append(
                OnlyEconomicFactManifest(
                    family,
                    only_canonical_fingerprint([item.to_dict() for item in selected]),
                    len(selected),
                    str(selected[0].data_version),
                    kind,
                )
            )
    binding = OnlyResearchDatasetEconomicBinding(
        snapshot.snapshot_fingerprint,
        composition_fingerprint,
        tuple(manifests),
    )
    OnlyDatasetEconomicBindingStore(layout.root).publish_verified(binding)
    OnlyBacktestEconomicFactStore(layout.root).publish(binding, economic_updates)
    config_path = output / f"binance-{name}.json"
    _write_exclusive(config_path, dict(config.normalized_payload))
    configuration = OnlyBacktestDeploymentCatalog((config,)).configuration_fingerprints[0]
    definition_document = _definition(definition)
    equivalence_evidence = _certify_strategy_calculations(
        definition_document,
        dataset_store,
        layout.research_root,
    )
    result = {
        "definition": definition_document,
        "backtest_request": _backtest_request(binding.fingerprint, configuration),
        "dataset_snapshot_fingerprint": snapshot.snapshot_fingerprint,
        "dataset_binding_fingerprint": binding.fingerprint,
        "market_product_configuration_fingerprint": configuration,
        "market_product_composition_fingerprint": composition_fingerprint,
        "revision_ids": list(revision_ids),
        "instruments": [str(item.instrument_id) for item in instruments],
        "row_count": snapshot.row_count,
        "calculation_equivalence_evidence_fingerprints": list(equivalence_evidence),
    }
    _write_exclusive(output / f"acceptance-{name}.json", result)
    return result


def provision(
    *,
    capture_path: Path,
    user_data_root: Path,
    output: Path,
    start: datetime,
    end: datetime,
    products: tuple[str, ...],
    spot_symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
) -> dict[str, object]:
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("GOLDEN_INTERVAL_INVALID")
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if start.second or start.microsecond or end.second or end.microsecond:
        raise ValueError("GOLDEN_INTERVAL_MUST_ALIGN_TO_MINUTES")
    raw = json.loads(capture_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("REFERENCE_CAPTURE_CORRUPT")
    spot_capture, usdm_capture = _capture_authorities(raw)
    selected_captures = [spot_capture if item == "spot" else usdm_capture for item in products]
    if any(item is None for item in selected_captures):
        raise ValueError("REFERENCE_CAPTURE_PRODUCT_MISSING")
    for capture in selected_captures:
        if capture is None:
            raise AssertionError("validated selected capture unexpectedly absent")
        captured_at = capture.captured_at
        if start < captured_at:
            raise ValueError(
                f"HISTORICAL_COVERAGE_UNPROVEN:start={start.isoformat()}:captured_at={captured_at.isoformat()}"
            )
    spot_http = OnlyBinancePublicHttpClient(_SPOT_URL, max_response_bytes=16 * 1024 * 1024)
    usdm_http = OnlyBinancePublicHttpClient(_USDM_URL, max_response_bytes=16 * 1024 * 1024)
    server_times = []
    if "spot" in products:
        server_times.append(_server_time(spot_http, "/api/v3/time"))
    if "usdm" in products:
        server_times.append(_server_time(usdm_http, "/fapi/v1/time"))
    if int(end.timestamp() * 1000) > min(value // 60_000 * 60_000 for value in server_times):
        raise ValueError("GOLDEN_INTERVAL_NOT_YET_CLOSED")

    postgres = OnlyPostgresConfig.from_environment()
    clickhouse = OnlyClickHouseClient(OnlyClickHouseConfig.from_environment())
    fact_store = OnlyClickHouseMarketFactStore(clickhouse)
    catalog = OnlyPostgresMarketDataCatalog(postgres.dsn)
    query = OnlyHistoricalMarketDataQueryService(catalog, fact_store)
    layout = OnlyUserDataLayout(user_data_root)
    _ensure_product_roots(layout)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    output.mkdir(parents=True, exist_ok=True)
    results: dict[str, object] = {}

    if spot_capture is not None and "spot" in products:
        provider = OnlyBinanceSpotBacktestResourceProvider()
        resource_id = f"sha256:{spot_capture.authority.identity.authority_fingerprint}"
        _write_exclusive(
            output / "binance-spot-reference.json",
            _resource_document(provider.provider_id, resource_id, provider.dump_reference(spot_capture.authority)),
        )
        requested_spot_symbols = tuple(dict.fromkeys(item.strip().upper() for item in spot_symbols if item.strip()))
        if not requested_spot_symbols:
            raise ValueError("BINANCE_SPOT_SYMBOLS_EMPTY")
        references_by_symbol = {item.raw_symbol: item for item in spot_capture.authority.references}
        missing_spot_symbols = tuple(item for item in requested_spot_symbols if item not in references_by_symbol)
        if missing_spot_symbols:
            raise ValueError(f"BINANCE_SPOT_REFERENCE_SYMBOL_MISSING:{','.join(missing_spot_symbols)}")
        instruments = tuple(_spot_instrument(references_by_symbol[item]) for item in requested_spot_symbols)
        revisions: list[str] = []
        scopes: list[OnlyMarketDataScope] = []
        for instrument in instruments:
            source = OnlyMarketDataSourceId("BINANCE_SPOT")
            version = OnlyDataVersion("BINANCE_SPOT_REST_V1")
            pages = _pages(
                spot_http,
                "/api/v3/klines",
                {"symbol": str(instrument.raw_symbol), "interval": "1m"},
                start_ms=start_ms,
                end_ms=end_ms,
                timestamp_field=0,
                page_size=1000,
            )
            bar_type = OnlyBarType(instrument.instrument_id, _BAR_SPEC, OnlyAggregationSource.EXTERNAL)
            updates = tuple(
                tuple(
                    _bar_update(only_normalize_rest_kline(row, instrument, bar_type), source, version)
                    for row in page.rows
                    if isinstance(row, list)
                )
                for page in pages
            )
            revision, scope = _persist_bars(
                pages=pages,
                page_updates=updates,
                instrument=instrument,
                source=source,
                version=version,
                market="SPOT",
                capture_session=f"{spot_capture.capture_fingerprint}:{instrument.instrument_id}",
                start=start,
                end=end,
                wal_root=user_data_root / "wal" / "a0" / str(instrument.instrument_id),
                store=fact_store,
                catalog=catalog,
            )
            revisions.append(revision)
            scopes.append(scope)
        market_config = {
            "plugin_id": "onlyalpha-plugin-binance-spot",
            "product_id": "BINANCE_SPOT",
            "product_version": "1",
            "config": {
                "reference_resource_id": resource_id,
                "expected_reference_fingerprint": spot_capture.authority.identity.authority_fingerprint,
                "maker_fee_rate": "0.001",
                "taker_fee_rate": "0.001",
            },
        }
        config = _product_document(
            product="spot", instruments=instruments, start=start, end=end, market_config=market_config
        )
        resources = OnlyBacktestMarketProductResourceRegistry({resource_id: spot_capture.authority})
        binding = OnlyBinanceSpotMarketProductFactory().resolve(
            config.market,
            OnlyMarketProductResolutionContext(resources, instruments),
        )
        dataset_definition = OnlyResearchDatasetDefinition(
            tuple(item.instrument_id for item in instruments),
            _BAR_SPEC,
            OnlyAggregationSource.EXTERNAL,
            _dataset_event_range(start, end),
            OnlyAdjustmentType.RAW,
        )
        results["spot"] = _publish_vertical(
            name="spot",
            instruments=instruments,
            revision_ids=tuple(revisions),
            scopes=tuple(scopes),
            composition_fingerprint=binding.composition_identity.fingerprint,
            config=config,
            definition=dataset_definition,
            economic_updates=(),
            layout=layout,
            query=query,
            output=output,
        )

    if usdm_capture is not None and "usdm" in products:
        usdm_provider = OnlyBinanceUsdmBacktestResourceProvider()
        public_id = f"sha256:{usdm_capture.public_authority.identity.authority_fingerprint}"
        account_id = f"sha256:{usdm_capture.account_authority.identity.authority_fingerprint}"
        _write_exclusive(
            output / "binance-usdm-public-reference.json",
            _resource_document(
                usdm_provider.provider_id,
                public_id,
                usdm_provider.dump_reference(usdm_capture.public_authority),
            ),
        )
        _write_exclusive(
            output / "binance-usdm-account-reference.json",
            _resource_document(
                usdm_provider.provider_id,
                account_id,
                usdm_provider.dump_reference(usdm_capture.account_authority),
            ),
        )
        public_reference = usdm_capture.public_authority.references[0]
        usdm_instrument = _usdm_instrument(public_reference)
        usdm_instruments = (usdm_instrument,)
        source = OnlyMarketDataSourceId("BINANCE_USDM")
        version = OnlyDataVersion("BINANCE_USDM_REST_V1")
        bar_pages = _pages(
            usdm_http,
            "/fapi/v1/klines",
            {"symbol": "BTCUSDT", "interval": "1m"},
            start_ms=start_ms,
            end_ms=end_ms,
            timestamp_field=0,
            page_size=1500,
        )
        bar_type = OnlyBarType(usdm_instrument.instrument_id, _BAR_SPEC, OnlyAggregationSource.EXTERNAL)
        bar_updates = tuple(
            tuple(
                _bar_update(only_normalize_binance_usdm_kline(row, usdm_instrument, bar_type), source, version)
                for row in page.rows
                if isinstance(row, list)
            )
            for page in bar_pages
        )
        revision, scope = _persist_bars(
            pages=bar_pages,
            page_updates=bar_updates,
            instrument=usdm_instrument,
            source=source,
            version=version,
            market="USDM",
            capture_session=f"{usdm_capture.capture_fingerprint}:{usdm_instrument.instrument_id}",
            start=start,
            end=end,
            wal_root=user_data_root / "wal" / "a0" / str(usdm_instrument.instrument_id),
            store=fact_store,
            catalog=catalog,
        )
        mark_pages = _pages(
            usdm_http,
            "/fapi/v1/markPriceKlines",
            {"symbol": "BTCUSDT", "interval": "1m"},
            start_ms=start_ms,
            end_ms=end_ms,
            timestamp_field=0,
            page_size=1500,
        )
        funding_pages = _pages(
            usdm_http,
            "/fapi/v1/fundingRate",
            {"symbol": "BTCUSDT"},
            start_ms=start_ms,
            end_ms=end_ms,
            timestamp_field="fundingTime",
            page_size=1000,
        )
        _persist_raw_pages(
            mark_pages,
            source=str(source),
            capture_session=usdm_capture.capture_fingerprint,
            market="USDM",
            stream="mark-price-1m",
            wal_root=user_data_root / "wal" / "a0" / "usdm-mark-raw",
            store=fact_store,
            catalog=catalog,
        )
        _persist_raw_pages(
            funding_pages,
            source=str(source),
            capture_session=usdm_capture.capture_fingerprint,
            market="USDM",
            stream="funding-rate",
            wal_root=user_data_root / "wal" / "a0" / "usdm-funding-raw",
            store=fact_store,
            catalog=catalog,
        )
        normalizer = OnlyBinanceUsdmHistoricalNormalizer()
        economic: list[OnlyMarketDataInboundUpdate] = []
        for page in mark_pages:
            received = datetime.fromtimestamp(page.received_ns / 1_000_000_000, tz=UTC)
            for row in page.rows:
                if not isinstance(row, list):
                    raise ValueError("BINANCE_MARK_ROW_INVALID")
                event_ms = int(str(row[0]))
                economic.append(
                    _fact_update(
                        normalizer.reference_price(
                            {"T": event_ms, "p": str(row[1])},
                            instrument_id=usdm_instrument.instrument_id,
                            kind=OnlyReferencePriceKind.MARK,
                            data_version=str(version),
                            source_sequence=event_ms,
                            received_at=received,
                        ),
                        source,
                        version,
                    )
                )
        for page in funding_pages:
            received = datetime.fromtimestamp(page.received_ns / 1_000_000_000, tz=UTC)
            for row in page.rows:
                if not isinstance(row, dict):
                    raise ValueError("BINANCE_FUNDING_ROW_INVALID")
                event_ms = int(str(row["fundingTime"]))
                economic.append(
                    _fact_update(
                        normalizer.funding_rate(
                            row,
                            instrument_id=usdm_instrument.instrument_id,
                            data_version=str(version),
                            source_sequence=event_ms,
                            received_at=received,
                        ),
                        source,
                        version,
                    )
                )
        economic_updates = tuple(
            sorted(economic, key=lambda item: (item.ts_event.unix_nanos, item.data_type.value, str(item.update_id)))
        )
        if not any(item.data_type is OnlyMarketDataType.FUNDING_RATE for item in economic_updates):
            raise ValueError("BINANCE_USDM_FUNDING_BOUNDARY_ABSENT")
        account_reference = usdm_capture.account_authority.references[0]
        effective = account_reference.effective_inputs
        market_config = {
            "plugin_id": "onlyalpha-plugin-binance-usdm",
            "product_id": "BINANCE_USDM",
            "product_version": "2",
            "config": {
                "public_reference_resource_id": public_id,
                "expected_public_reference_fingerprint": usdm_capture.public_authority.identity.authority_fingerprint,
                "account_reference_resource_id": account_id,
                "expected_account_reference_fingerprint": usdm_capture.account_authority.identity.authority_fingerprint,
                "requested_position_mode": effective.position_mode.value,
                "requested_margin_mode": effective.margin_mode.value,
                "requested_leverage": str(effective.leverage),
                "maker_fee_rate": "0.0002",
                "taker_fee_rate": "0.0005",
            },
        }
        config = _product_document(
            product="usdm", instruments=usdm_instruments, start=start, end=end, market_config=market_config
        )
        resources = OnlyBacktestMarketProductResourceRegistry(
            {public_id: usdm_capture.public_authority, account_id: usdm_capture.account_authority}
        )
        product_binding = OnlyBinanceUsdmMarketProductFactory().resolve(
            config.market,
            OnlyMarketProductResolutionContext(resources, usdm_instruments),
        )
        dataset_definition = OnlyResearchDatasetDefinition(
            (usdm_instrument.instrument_id,),
            _BAR_SPEC,
            OnlyAggregationSource.EXTERNAL,
            _dataset_event_range(start, end),
            OnlyAdjustmentType.RAW,
        )
        results["usdm"] = _publish_vertical(
            name="usdm",
            instruments=usdm_instruments,
            revision_ids=(revision,),
            scopes=(scope,),
            composition_fingerprint=product_binding.composition_identity.fingerprint,
            config=config,
            definition=dataset_definition,
            economic_updates=economic_updates,
            layout=layout,
            query=query,
            output=output,
        )
    manifest = {
        "schema_version": 1,
        "provider": "BINANCE",
        "environment": "LIVE",
        "interval": {"start": start.isoformat(), "end": end.isoformat()},
        "reference_capture": str(capture_path),
        "verticals": results,
    }
    _write_exclusive(output / "provisioned-manifest.json", manifest)
    return manifest


def _products(value: str) -> tuple[str, ...]:
    return ("spot", "usdm") if value == "all" else (value,)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provision-a0-binance-golden")
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture-reference")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--products", choices=("spot", "usdm", "all"), default="all")
    provision_parser = subparsers.add_parser("provision")
    provision_parser.add_argument("--capture", type=Path, required=True)
    provision_parser.add_argument("--user-data-root", type=Path, required=True)
    provision_parser.add_argument("--output", type=Path, required=True)
    provision_parser.add_argument("--start", type=datetime.fromisoformat, required=True)
    provision_parser.add_argument("--end", type=datetime.fromisoformat, required=True)
    provision_parser.add_argument("--products", choices=("spot", "usdm", "all"), default="all")
    provision_parser.add_argument("--spot-symbol", action="append")
    args = parser.parse_args(argv)
    result: dict[str, object]
    if args.command == "capture-reference":
        captured = capture_reference(args.output, products=_products(args.products))
        result = {
            "capture_path": str(args.output),
            "products": {
                name: {
                    "captured_at": value["captured_at"],
                    "capture_fingerprint": value["capture_fingerprint"],
                }
                for name, value in captured.items()
                if name in {"spot", "usdm"} and isinstance(value, dict)
            },
        }
    else:
        result = provision(
            capture_path=args.capture,
            user_data_root=args.user_data_root,
            output=args.output,
            start=args.start,
            end=args.end,
            products=_products(args.products),
            spot_symbols=tuple(args.spot_symbol or ("BTCUSDT", "ETHUSDT")),
        )
    print(only_canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
