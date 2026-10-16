"""Bounded provider discovery and operational quotes, never sealed market facts."""

from __future__ import annotations

import pickle
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from onlyalpha.application.market_data_product import (
    OnlyMarketDataInstrumentProjectionV1,
    OnlyMarketDataProductError,
    OnlyMarketDataProductService,
    OnlyMarketDataSourceReferenceV1,
    OnlyMarketDataSourceSelectionV1,
    OnlyResolvedMarketDataRuntime,
)
from onlyalpha.application.source_read_access import OnlySourceReadPermission, OnlySourceReadSession
from onlyalpha.domain.enums import OnlyAssetClass, OnlyInstrumentType
from onlyalpha.plugin.data_source import (
    OnlyDataSourceDiscovery,
    OnlyDataSourceDiscoveryCapabilitiesV1,
    OnlyDataSourceInstrumentCatalogRequestV1,
    OnlyDataSourceInstrumentV1,
    OnlyDataSourceQuoteRequestV1,
    OnlyDataSourceQuotes,
    OnlyDataSourceQuoteV1,
)

DiscoveryStatus = Literal["COMPLETE", "TIMEOUT", "UNAVAILABLE", "UNSUPPORTED"]
_MAX_CATALOGUE = 10000
# One process budget across all browser requests; a timed-out provider cannot keep running.
_PROVIDER_SLOTS = threading.BoundedSemaphore(4)


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSearchResultV1:
    source_selection: OnlyMarketDataSourceSelectionV1
    instrument: OnlyMarketDataInstrumentProjectionV1


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSearchSourceV1:
    source_selection: OnlyMarketDataSourceSelectionV1
    status: DiscoveryStatus
    asset_classes: tuple[str, ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSearchProjectionV1:
    results: tuple[OnlyMarketDataSearchResultV1, ...]
    sources: tuple[OnlyMarketDataSearchSourceV1, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class OnlyMarketDataQuoteProjectionV1:
    instrument_id: str
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    last_price: str | None = None
    change_pct: str | None = None
    change_basis: Literal["ROLLING_24H", "PREVIOUS_CLOSE"] | None = None
    ts_event_ns: int | None = None


@dataclass(frozen=True, slots=True)
class OnlyMarketDataQuoteListProjectionV1:
    source_selection: OnlyMarketDataSourceSelectionV1
    quotes: tuple[OnlyMarketDataQuoteProjectionV1, ...]
    status: DiscoveryStatus


def _provider_call(
    factory: object, operation: str, request: object, deadline: float
) -> tuple[DiscoveryStatus, tuple[object, ...]]:
    if not _PROVIDER_SLOTS.acquire(timeout=max(0, deadline - time.monotonic())):
        return "TIMEOUT", ()
    process: subprocess.Popen[bytes] | None = None
    try:
        if time.monotonic() >= deadline:
            return "TIMEOUT", ()
        # A service __main__ factory cannot be imported without replaying startup.
        factory_type = type(factory)
        if factory_type.__module__ == "__main__" or "<locals>" in factory_type.__qualname__:
            return "UNAVAILABLE", ()
        payload = pickle.dumps((factory, operation, request))
        if len(payload) > 16 * 1024 * 1024:
            return "UNAVAILABLE", ()
        process = subprocess.Popen(
            [sys.executable, "-m", "onlyalpha.application.market_data_discovery_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        response, _ = process.communicate(input=payload, timeout=max(0, deadline - time.monotonic()))
        if process.returncode != 0 or len(response) > 16 * 1024 * 1024:
            return "UNAVAILABLE", ()
        status, result = pickle.loads(response)
        if status not in ("COMPLETE", "UNAVAILABLE", "UNSUPPORTED") or not isinstance(result, tuple):
            return "UNAVAILABLE", ()
        return status, result
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ()
    except Exception:
        return "UNAVAILABLE", ()
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        # An unreaped process retains its slot rather than permitting unbounded successors.
        if process is None or process.poll() is not None:
            _PROVIDER_SLOTS.release()


def _instrument(item: OnlyDataSourceInstrumentV1) -> OnlyMarketDataInstrumentProjectionV1:
    return OnlyMarketDataInstrumentProjectionV1(
        str(item.instrument.instrument_id),
        item.display_symbol,
        item.venue,
        item.market,
        item.instrument.asset_class.value,
        item.instrument.instrument_type.value,
        item.instrument.status.value,
        item.market_data_capabilities,
    )


class OnlyMarketDataDiscoveryService:
    """Read-only provider projections with a bounded, disposable catalogue cache."""

    def __init__(self, market_data: OnlyMarketDataProductService) -> None:
        self._market_data = market_data
        self._cache: OrderedDict[
            tuple[str, str, str],
            tuple[float, OnlyDataSourceDiscoveryCapabilitiesV1, tuple[OnlyDataSourceInstrumentV1, ...] | None],
        ] = OrderedDict()
        self._cache_lock = threading.Lock()

    def search(
        self,
        *,
        query: str,
        asset_class: str | None = None,
        limit: int = 25,
        instrument_types: tuple[str, ...] = (),
        read_session: OnlySourceReadSession | None = None,
    ) -> OnlyMarketDataSearchProjectionV1:
        if not query.strip() or len(query) > 128 or not 1 <= limit <= 25:
            raise OnlyMarketDataProductError("MARKET_DATA_SEARCH_REQUEST_INVALID")
        if asset_class is not None and asset_class not in {item.value for item in OnlyAssetClass}:
            raise OnlyMarketDataProductError("MARKET_DATA_SEARCH_REQUEST_INVALID")
        if any(item not in {kind.value for kind in OnlyInstrumentType} for item in instrument_types):
            raise OnlyMarketDataProductError("MARKET_DATA_SEARCH_REQUEST_INVALID")
        sources = self._market_data.list_sources(read_session=read_session)
        # Resolve all exact proofs on the caller; never share a read session with provider workers.
        runtimes = tuple(
            self._market_data.resolve_read_runtime(
                OnlyMarketDataSourceReferenceV1(
                    source.integration_id, source.integration_revision_fingerprint, source.type_id
                ),
                read_session=read_session,
            )
            for source in sources
        )
        deadline = time.monotonic() + 10.0
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="market-discovery") as executor:
            futures = [
                executor.submit(
                    self._search_source, runtime, query.strip(), asset_class, instrument_types, limit, deadline
                )
                for runtime in runtimes
            ]
            responses = [future.result() for future in futures]
        for runtime in runtimes:
            current = self._market_data.resolve_read_runtime(
                OnlyMarketDataSourceReferenceV1(
                    runtime.selection.integration_id,
                    runtime.selection.integration_revision_fingerprint,
                    runtime.selection.type_id,
                ),
                read_session=read_session,
            )
            if current.selection != runtime.selection or current.binding_fingerprint != runtime.binding_fingerprint:
                raise OnlyMarketDataProductError("MARKET_DATA_SOURCE_SELECTION_MISMATCH")
        results = tuple(item for _, found in responses for item in found)
        return OnlyMarketDataSearchProjectionV1(
            results[:limit],
            tuple(source for source, _ in responses),
            len(results) > limit or any(source.truncated for source, _ in responses),
        )

    def _search_source(
        self,
        runtime: OnlyResolvedMarketDataRuntime,
        query: str,
        asset_class: str | None,
        instrument_types: tuple[str, ...],
        limit: int,
        deadline: float,
    ) -> tuple[OnlyMarketDataSearchSourceV1, tuple[OnlyMarketDataSearchResultV1, ...]]:
        factory = runtime.factory
        if not isinstance(factory, OnlyDataSourceDiscovery):
            return OnlyMarketDataSearchSourceV1(runtime.selection, "UNSUPPORTED", ()), ()
        deadline = min(deadline, time.monotonic() + 8)
        key = (
            runtime.selection.integration_id,
            runtime.selection.integration_revision_fingerprint,
            runtime.binding_fingerprint,
        )
        capabilities = None
        cached = None
        with self._cache_lock:
            if key in self._cache:
                expiry, capabilities, cached = self._cache[key]
                if expiry <= time.monotonic():
                    del self._cache[key]
                    capabilities, cached = None, None
                else:
                    self._cache.move_to_end(key)
        if capabilities is None:
            status, response = _provider_call(
                factory,
                "discovery",
                OnlyDataSourceInstrumentCatalogRequestV1(
                    runtime.plugin_config,
                    query=query,
                    asset_class=asset_class,
                    instrument_types=instrument_types,
                    limit=limit + 1,
                    deadline_monotonic=deadline,
                ),
                deadline,
            )
            if (
                status != "COMPLETE"
                or len(response) != 2
                or type(response[0]) is not OnlyDataSourceDiscoveryCapabilitiesV1
                or (response[1] is not None and not isinstance(response[1], tuple))
            ):
                return OnlyMarketDataSearchSourceV1(
                    runtime.selection, status if status != "COMPLETE" else "UNAVAILABLE", ()
                ), ()
            capabilities = response[0]
            cached = cast(tuple[OnlyDataSourceInstrumentV1, ...] | None, response[1])
            with self._cache_lock:
                self._cache[key] = (
                    time.monotonic() + 60,
                    capabilities,
                    cached if capabilities.catalogue_snapshot else None,
                )
                while len(self._cache) > 32:
                    self._cache.popitem(last=False)
        if asset_class is not None and asset_class not in capabilities.asset_classes:
            return OnlyMarketDataSearchSourceV1(runtime.selection, "COMPLETE", capabilities.asset_classes), ()
        snapshot = capabilities.catalogue_snapshot
        status = "COMPLETE"
        if cached is None:
            status, response = _provider_call(
                factory,
                "instruments",
                OnlyDataSourceInstrumentCatalogRequestV1(
                    runtime.plugin_config,
                    query="" if snapshot else query,
                    limit=_MAX_CATALOGUE + 1 if snapshot else limit + 1,
                    asset_class=None if snapshot else asset_class,
                    instrument_types=() if snapshot else instrument_types,
                    deadline_monotonic=deadline,
                    snapshot=snapshot,
                ),
                deadline,
            )
            cached = cast(tuple[OnlyDataSourceInstrumentV1, ...], response)
            if status == "COMPLETE" and snapshot:
                with self._cache_lock:
                    self._cache[key] = (time.monotonic() + 60, capabilities, cached)
                    while len(self._cache) > 32:
                        self._cache.popitem(last=False)
        if status != "COMPLETE":
            return OnlyMarketDataSearchSourceV1(runtime.selection, status, capabilities.asset_classes), ()
        try:
            if any(
                item.venue != runtime.venue
                or item.market != runtime.market
                or str(item.instrument.venue) != runtime.venue
                for item in cached
            ) or len({str(item.instrument.instrument_id) for item in cached}) != len(cached):
                return OnlyMarketDataSearchSourceV1(runtime.selection, "UNAVAILABLE", capabilities.asset_classes), ()
            # Snapshot providers declare literal-symbol matching. Filter before any result limit.
            selected = tuple(
                item
                for item in cached
                if (asset_class is None or item.instrument.asset_class.value == asset_class)
                and (not instrument_types or item.instrument.instrument_type.value in instrument_types)
                and (
                    not snapshot
                    or query.casefold() in item.display_symbol.casefold()
                    or query.casefold() in str(item.instrument.instrument_id).casefold()
                )
            )
            truncated = len(selected) > limit or (snapshot and len(cached) > _MAX_CATALOGUE)
            return (
                OnlyMarketDataSearchSourceV1(runtime.selection, status, capabilities.asset_classes, truncated),
                tuple(OnlyMarketDataSearchResultV1(runtime.selection, _instrument(item)) for item in selected[:limit]),
            )
        except (AttributeError, TypeError, ValueError):
            return OnlyMarketDataSearchSourceV1(runtime.selection, "UNAVAILABLE", capabilities.asset_classes), ()

    def quotes(
        self,
        reference: OnlyMarketDataSourceReferenceV1,
        *,
        instrument_ids: tuple[str, ...],
        read_session: OnlySourceReadSession | None = None,
    ) -> OnlyMarketDataQuoteListProjectionV1:
        if not 1 <= len(instrument_ids) <= 25 or len(set(instrument_ids)) != len(instrument_ids):
            raise OnlyMarketDataProductError("MARKET_DATA_QUOTE_REQUEST_INVALID")
        runtime = self._market_data.resolve_read_runtime(
            reference,
            read_session=read_session,
            permission=OnlySourceReadPermission.REALTIME_PREVIEW,
        )
        empty = tuple(OnlyMarketDataQuoteProjectionV1(item, "UNAVAILABLE") for item in instrument_ids)
        if not isinstance(runtime.factory, OnlyDataSourceQuotes):
            return OnlyMarketDataQuoteListProjectionV1(runtime.selection, empty, "UNSUPPORTED")
        deadline = time.monotonic() + 8
        status, response = _provider_call(
            runtime.factory,
            "quotes",
            OnlyDataSourceQuoteRequestV1(
                runtime.plugin_config,
                instrument_ids,
                deadline,
            ),
            deadline,
        )
        current = self._market_data.resolve_read_runtime(
            reference,
            read_session=read_session,
            permission=OnlySourceReadPermission.REALTIME_PREVIEW,
        )
        if current.selection != runtime.selection or current.binding_fingerprint != runtime.binding_fingerprint:
            raise OnlyMarketDataProductError("MARKET_DATA_SOURCE_SELECTION_MISMATCH")

        found: dict[str, OnlyMarketDataQuoteProjectionV1] = {}
        try:
            for quote in cast(tuple[OnlyDataSourceQuoteV1, ...], response):
                if (
                    quote.instrument_id not in instrument_ids
                    or quote.instrument_id in found
                    or not isinstance(quote.last_price, str)
                    or not Decimal(quote.last_price).is_finite()
                    or type(quote.ts_event_ns) is not int
                    or quote.ts_event_ns <= 0
                    or (quote.change_pct is None) != (quote.change_basis is None)
                    or (
                        quote.change_pct is not None
                        and (not isinstance(quote.change_pct, str) or not Decimal(quote.change_pct).is_finite())
                    )
                    or quote.change_basis not in (None, "ROLLING_24H", "PREVIOUS_CLOSE")
                ):
                    raise ValueError("MARKET_DATA_QUOTE_RESPONSE_INVALID")
                found[quote.instrument_id] = OnlyMarketDataQuoteProjectionV1(
                    quote.instrument_id,
                    "AVAILABLE",
                    quote.last_price,
                    quote.change_pct,
                    cast(Literal["ROLLING_24H", "PREVIOUS_CLOSE"] | None, quote.change_basis),
                    quote.ts_event_ns,
                )
        except (ValueError, TypeError, InvalidOperation):
            return OnlyMarketDataQuoteListProjectionV1(runtime.selection, empty, "UNAVAILABLE")
        return OnlyMarketDataQuoteListProjectionV1(
            runtime.selection,
            tuple(found.get(item.instrument_id, item) for item in empty),
            status,
        )
