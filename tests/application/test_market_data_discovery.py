"""Operational discovery never turns unavailable provider proof into empty success."""

from __future__ import annotations

import multiprocessing
import time
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from onlyalpha.application import market_data_discovery as discovery
from onlyalpha.application.market_data_product import (
    OnlyMarketDataProductService,
    OnlyMarketDataSourceReferenceV1,
    OnlyMarketDataSourceSelectionV1,
    OnlyResolvedMarketDataRuntime,
)
from onlyalpha.domain.enums import OnlyAssetClass, OnlyCurrencyType, OnlyInstrumentType, OnlyMarketType
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRawSymbol
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity
from onlyalpha.plugin.data_source import (
    OnlyDataSourceDiscoveryCapabilitiesV1,
    OnlyDataSourceInstrumentCatalogRequestV1,
    OnlyDataSourceInstrumentV1,
    OnlyDataSourceQuoteRequestV1,
    OnlyDataSourceQuoteV1,
)


class Factory:
    def discovery_capabilities(self, config: object) -> OnlyDataSourceDiscoveryCapabilitiesV1:
        return OnlyDataSourceDiscoveryCapabilitiesV1(("CRYPTOCURRENCY",), catalogue_snapshot=True, quotes=True)

    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        return ()

    def quotes(self, request: OnlyDataSourceQuoteRequestV1) -> tuple[OnlyDataSourceQuoteV1, ...]:
        return ()


class BlockingFactory(Factory):
    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        multiprocessing.Event().wait()
        return ()


class EnteredBlockingFactory(BlockingFactory):
    def __init__(self, marker: str) -> None:
        self.marker = marker

    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        from pathlib import Path

        Path(self.marker).write_text("callback entered")
        return super().list_instruments(request)


SELECTION = OnlyMarketDataSourceSelectionV1("source", "a" * 64, "test.market", "venue.live", "LIVE")
REFERENCE = OnlyMarketDataSourceReferenceV1("source", "a" * 64, "test.market")


def runtime(selection: OnlyMarketDataSourceSelectionV1 = SELECTION) -> OnlyResolvedMarketDataRuntime:
    return cast(
        OnlyResolvedMarketDataRuntime,
        SimpleNamespace(
            selection=selection,
            binding_fingerprint="b" * 64,
            factory=Factory(),
            plugin_config=None,
            venue="VENUE",
            market="SPOT",
        ),
    )


def instrument(symbol: str) -> OnlyDataSourceInstrumentV1:
    currency = OnlyCurrency("USD", 2, OnlyCurrencyType.CRYPTO)
    return OnlyDataSourceInstrumentV1(
        OnlyInstrument(
            instrument_id=OnlyInstrumentId.parse(f"{symbol}.VENUE"),
            raw_symbol=OnlyRawSymbol(symbol),
            asset_class=OnlyAssetClass.CRYPTOCURRENCY,
            instrument_type=OnlyInstrumentType.CRYPTO_SPOT,
            market_type=OnlyMarketType.CASH,
            quote_currency=currency,
            settlement_currency=currency,
            price_precision=2,
            quantity_precision=2,
            tick_size=OnlyPrice(Decimal("0.01"), 2),
            step_size=OnlyQuantity(Decimal("0.01"), 2),
        ),
        symbol,
        "VENUE",
        "SPOT",
        ("BAR_1M_EXTERNAL_RAW",),
    )


def service(runtimes: list[OnlyResolvedMarketDataRuntime]) -> discovery.OnlyMarketDataDiscoveryService:
    class MarketData:
        def list_sources(self, **kwargs: object) -> tuple[object, ...]:
            return tuple(
                SimpleNamespace(
                    integration_id=item.selection.integration_id,
                    integration_revision_fingerprint=item.selection.integration_revision_fingerprint,
                    type_id=item.selection.type_id,
                )
                for item in runtimes
            )

        def resolve_read_runtime(
            self, reference: OnlyMarketDataSourceReferenceV1, **kwargs: object
        ) -> OnlyResolvedMarketDataRuntime:
            from onlyalpha.application.source_read_access import OnlySourceReadPermission, OnlySourceReadSession

            session = kwargs.get("read_session")
            permission = kwargs.get("permission", OnlySourceReadPermission.CLOSED_HISTORY)
            result = next(item for item in runtimes if item.selection.integration_id == reference.integration_id)
            if isinstance(session, OnlySourceReadSession):
                session.require_reference(reference, permission)
                session.require_selection(result.selection, permission)
            return result

    return discovery.OnlyMarketDataDiscoveryService(cast(OnlyMarketDataProductService, MarketData()))


def test_filter_before_limit_cache_and_exact_binding_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def provider(*args: object) -> tuple[str, tuple[OnlyDataSourceInstrumentV1, ...]]:
        calls.append(args)
        instruments = (instrument("AAAUSD"), instrument("ETHUSD"), instrument("ETHUSDT"))
        return "COMPLETE", (
            (Factory().discovery_capabilities(None), instruments) if args[1] == "discovery" else instruments
        )

    monkeypatch.setattr(discovery, "_provider_call", provider)
    runtimes = [runtime()]
    application = service(runtimes)
    result = application.search(query="ETH", limit=1)
    assert result.results[0].instrument.display_symbol == "ETHUSD"
    assert result.truncated and result.sources[0].truncated
    assert application.search(query="USDT").results[0].instrument.display_symbol == "ETHUSDT"
    assert len(calls) == 1
    assert not application.search(query="ETH", asset_class="EQUITY").results
    assert len(calls) == 1
    runtimes[0] = runtime(replace(SELECTION, integration_revision_fingerprint="c" * 64))
    application.search(query="ETH")
    assert len(calls) == 2


def test_partial_timeout_never_becomes_empty_success(monkeypatch: pytest.MonkeyPatch) -> None:
    two = runtime(replace(SELECTION, integration_id="second"))
    two.plugin_config = "timeout"

    def provider(factory: object, op: str, request: object, deadline: float) -> tuple[str, tuple]:
        if request.plugin_config == "timeout":
            return "TIMEOUT", ()
        instruments = (instrument("BTCUSD"),)
        return "COMPLETE", ((Factory().discovery_capabilities(None), instruments) if op == "discovery" else instruments)

    monkeypatch.setattr(discovery, "_provider_call", provider)
    result = service([runtime(), two]).search(query="BTC")
    assert len(result.results) == 1
    assert [item.status for item in result.sources] == ["COMPLETE", "TIMEOUT"]


def test_quote_missing_ids_are_explicit_and_invalid_numbers_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        discovery,
        "_provider_call",
        lambda *args: ("COMPLETE", (OnlyDataSourceQuoteV1("BTCUSD.VENUE", "100.25", "1.0", "ROLLING_24H", 123),)),
    )
    application = service([runtime()])
    result = application.quotes(REFERENCE, instrument_ids=("BTCUSD.VENUE", "ETHUSD.VENUE"))
    assert [item.status for item in result.quotes] == ["AVAILABLE", "UNAVAILABLE"]
    assert result.quotes[0].change_basis == "ROLLING_24H"
    monkeypatch.setattr(
        discovery,
        "_provider_call",
        lambda *args: ("COMPLETE", (OnlyDataSourceQuoteV1("BTCUSD.VENUE", "NaN", "1.0", "ROLLING_24H", 123),)),
    )
    invalid = application.quotes(REFERENCE, instrument_ids=("BTCUSD.VENUE",))
    assert invalid.status == "UNAVAILABLE" and invalid.quotes[0].last_price is None


def test_uncooperative_provider_is_killed_and_reaped(monkeypatch: pytest.MonkeyPatch) -> None:
    started = []
    popen = discovery.subprocess.Popen

    def launch(*args, **kwargs):
        process = popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(discovery.subprocess, "Popen", launch)
    request = OnlyDataSourceInstrumentCatalogRequestV1(None, query="BTC")
    status, result = discovery._provider_call(BlockingFactory(), "instruments", request, time.monotonic() + 0.5)
    assert (status, result) == ("TIMEOUT", ())
    assert len(started) == 1 and started[0].poll() is not None


class RoundtripFactory(Factory):
    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        return (instrument("BTCUSD"),)


def test_successful_provider_roundtrip_is_reaped() -> None:
    status, result = discovery._provider_call(
        RoundtripFactory(),
        "instruments",
        OnlyDataSourceInstrumentCatalogRequestV1(None, query="BTC"),
        time.monotonic() + 8,
    )
    assert status == "COMPLETE"
    assert result == (instrument("BTCUSD"),)


def test_nonreturning_callback_is_terminated_after_it_has_actually_entered(tmp_path) -> None:
    marker = tmp_path / "provider-entered"
    status, result = discovery._provider_call(
        EnteredBlockingFactory(str(marker)),
        "instruments",
        OnlyDataSourceInstrumentCatalogRequestV1(None, query="BTC"),
        time.monotonic() + 8,
    )
    assert marker.read_text() == "callback entered"
    assert (status, result) == ("TIMEOUT", ())


def test_instrument_type_filter_runs_before_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        discovery,
        "_provider_call",
        lambda *args: (
            "COMPLETE",
            (
                (Factory().discovery_capabilities(None), (instrument("BTCUSD"),))
                if args[1] == "discovery"
                else (instrument("BTCUSD"),)
            ),
        ),
    )
    application = service([runtime()])
    assert not application.search(query="BTC", instrument_types=("FUTURE",)).results
    assert application.search(query="BTC", instrument_types=("CRYPTO_SPOT",)).results


def test_permission_withdrawal_while_fetching_discards_provider_results(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    from onlyalpha.application.source_read_access import (
        OnlySourceReadAccessError,
        OnlySourceReadAuthority,
        OnlySourceReadGrant,
        OnlySourceReadPermission,
    )

    token = "d" * 64
    grant = OnlySourceReadGrant(
        "source", "a" * 64, "test.market", "venue.live", "LIVE", (OnlySourceReadPermission.CLOSED_HISTORY,)
    )
    authority = OnlySourceReadAuthority("human", hashlib.sha256(token.encode()).hexdigest(), (grant,))
    session = authority.authenticate("Bearer " + token)

    def provider(*args: object) -> tuple[str, tuple[OnlyDataSourceInstrumentV1, ...]]:
        authority.withdraw()
        return "COMPLETE", (Factory().discovery_capabilities(None), (instrument("BTCUSD"),))

    monkeypatch.setattr(discovery, "_provider_call", provider)
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_UNAUTHORIZED"):
        service([runtime()]).search(query="BTC", read_session=session)


def test_source_change_during_query_discards_results(monkeypatch: pytest.MonkeyPatch) -> None:
    from onlyalpha.application.market_data_product import OnlyMarketDataProductError

    runtimes = [runtime()]

    def provider(*args: object) -> tuple[str, tuple[OnlyDataSourceInstrumentV1, ...]]:
        replacement = runtime()
        object.__setattr__(replacement, "binding_fingerprint", "e" * 64)
        runtimes[0] = replacement
        return "COMPLETE", (Factory().discovery_capabilities(None), (instrument("BTCUSD"),))

    monkeypatch.setattr(discovery, "_provider_call", provider)
    with pytest.raises(OnlyMarketDataProductError, match="MARKET_DATA_SOURCE_SELECTION_MISMATCH"):
        service(runtimes).search(query="BTC")


class BlockingCapabilitiesFactory(Factory):
    def discovery_capabilities(self, config: object) -> OnlyDataSourceDiscoveryCapabilitiesV1:
        multiprocessing.Event().wait()
        raise AssertionError("unreachable")


def test_blocked_capability_callback_does_not_hide_other_source_success() -> None:
    blocked = runtime(replace(SELECTION, integration_id="blocked"))
    object.__setattr__(blocked, "factory", BlockingCapabilitiesFactory())
    successful = runtime()
    object.__setattr__(successful, "factory", RoundtripFactory())
    result = service([blocked, successful]).search(query="BTC")
    assert [source.status for source in result.sources] == ["TIMEOUT", "COMPLETE"]
    assert result.results[0].instrument.display_symbol == "BTCUSD"
    assert not multiprocessing.active_children()


def test_universal_quote_projection_preserves_finite_negative_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        discovery,
        "_provider_call",
        lambda *args: ("COMPLETE", (OnlyDataSourceQuoteV1("OIL.VENUE", "-37.63", "-150", "PREVIOUS_CLOSE", 123),)),
    )
    result = service([runtime()]).quotes(REFERENCE, instrument_ids=("OIL.VENUE",))
    assert result.status == "COMPLETE"
    assert result.quotes[0].last_price == "-37.63"


class MalformedFactory(Factory):
    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        item = instrument("BADUSD")
        object.__setattr__(item.instrument, "asset_class", "CRYPTOCURRENCY")
        return (item,)


def test_malformed_instrument_does_not_hide_healthy_source() -> None:
    malformed = runtime(replace(SELECTION, integration_id="malformed"))
    object.__setattr__(malformed, "factory", MalformedFactory())
    successful = runtime()
    object.__setattr__(successful, "factory", RoundtripFactory())
    result = service([malformed, successful]).search(query="USD")
    assert [source.status for source in result.sources] == ["UNAVAILABLE", "COMPLETE"]
    assert result.results[0].instrument.display_symbol == "BTCUSD"


class CatalogueOnlyFactory(Factory):
    def discovery_capabilities(self, config: object) -> OnlyDataSourceDiscoveryCapabilitiesV1:
        return OnlyDataSourceDiscoveryCapabilitiesV1(("CRYPTOCURRENCY",), catalogue_snapshot=True, quotes=False)

    def quotes(self, request: OnlyDataSourceQuoteRequestV1) -> tuple[OnlyDataSourceQuoteV1, ...]:
        raise AssertionError("a declared unavailable capability must not run")


def test_quote_request_honours_provider_capability_declaration() -> None:
    status, result = discovery._provider_call(
        CatalogueOnlyFactory(),
        "quotes",
        OnlyDataSourceQuoteRequestV1(None, ("BTCUSD.VENUE",), time.monotonic() + 8),
        time.monotonic() + 8,
    )
    assert (status, result) == ("UNSUPPORTED", ())


class SubtypeFactory(Factory):
    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        from onlyalpha.domain.instrument import OnlyCryptoSpot

        item = instrument("BTCUSD")
        base = item.instrument
        subtype = OnlyCryptoSpot(
            instrument_id=base.instrument_id,
            raw_symbol=base.raw_symbol,
            market_type=base.market_type,
            quote_currency=base.quote_currency,
            settlement_currency=base.settlement_currency,
            base_currency=OnlyCurrency("BTC", 2, OnlyCurrencyType.CRYPTO),
            price_precision=base.price_precision,
            quantity_precision=base.quantity_precision,
            tick_size=base.tick_size,
            step_size=base.step_size,
        )
        return (replace(item, instrument=subtype),)


def test_canonical_instrument_subtype_crosses_spawn_boundary() -> None:
    status, result = discovery._provider_call(
        SubtypeFactory(),
        "instruments",
        OnlyDataSourceInstrumentCatalogRequestV1(None, query="BTC"),
        time.monotonic() + 8,
    )
    from onlyalpha.domain.instrument import OnlyCryptoSpot

    assert status == "COMPLETE"
    assert isinstance(result[0].instrument, OnlyCryptoSpot)


def test_quote_requires_realtime_grant_and_accepts_realtime_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    from onlyalpha.application.source_read_access import (
        OnlySourceReadAccessError,
        OnlySourceReadAuthority,
        OnlySourceReadGrant,
        OnlySourceReadPermission,
    )

    token = "d" * 64
    calls = []

    def provider(*args: object) -> tuple[str, tuple[OnlyDataSourceQuoteV1, ...]]:
        calls.append(args)
        return "COMPLETE", (OnlyDataSourceQuoteV1("BTCUSD.VENUE", "100", "1", "ROLLING_24H", 123),)

    monkeypatch.setattr(discovery, "_provider_call", provider)

    def session(permission: OnlySourceReadPermission):
        grant = OnlySourceReadGrant("source", "a" * 64, "test.market", "venue.live", "LIVE", (permission,))
        return OnlySourceReadAuthority("human", hashlib.sha256(token.encode()).hexdigest(), (grant,)).authenticate(
            "Bearer " + token
        )

    result = service([runtime()]).quotes(
        REFERENCE, instrument_ids=("BTCUSD.VENUE",), read_session=session(OnlySourceReadPermission.REALTIME_PREVIEW)
    )
    assert result.quotes[0].status == "AVAILABLE" and len(calls) == 1
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_FORBIDDEN"):
        service([runtime()]).quotes(
            REFERENCE, instrument_ids=("BTCUSD.VENUE",), read_session=session(OnlySourceReadPermission.CLOSED_HISTORY)
        )
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["catalogue_snapshot", "quotes"])
def test_discovery_capability_flags_require_actual_booleans(field: str) -> None:
    with pytest.raises(ValueError, match="DATA_SOURCE_DISCOVERY_CAPABILITIES_INVALID"):
        OnlyDataSourceDiscoveryCapabilitiesV1(("CRYPTOCURRENCY",), **{field: "false"})


def test_discovery_asset_classes_require_immutable_tuple() -> None:
    with pytest.raises(ValueError, match="DATA_SOURCE_DISCOVERY_CAPABILITIES_INVALID"):
        OnlyDataSourceDiscoveryCapabilitiesV1(["CRYPTOCURRENCY"])


def test_cold_search_uses_one_bounded_worker_for_capabilities_and_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def provider(factory: object, operation: str, request: object, deadline: float):
        calls.append(operation)
        capabilities = Factory().discovery_capabilities(None)
        instruments = (instrument("BTCUSD"),)
        if operation == "discovery":
            return "COMPLETE", (capabilities, instruments)
        if operation == "capabilities":
            return "COMPLETE", (capabilities,)
        return "COMPLETE", instruments

    monkeypatch.setattr(discovery, "_provider_call", provider)
    application = service([runtime()])
    assert application.search(query="BTC").results[0].instrument.display_symbol == "BTCUSD"
    assert calls == ["discovery"]
    application.search(query="USD")
    assert calls == ["discovery"]


def test_unsupported_category_does_not_cache_an_unfetched_empty_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def provider(factory: object, operation: str, request: object, deadline: float):
        calls.append(operation)
        if operation == "discovery":
            assert request.asset_class == "EQUITY"
            return "COMPLETE", (Factory().discovery_capabilities(None), None)
        assert request.snapshot and request.query == ""
        return "COMPLETE", (instrument("BTCUSD"),)

    monkeypatch.setattr(discovery, "_provider_call", provider)
    application = service([runtime()])
    assert not application.search(query="BTC", asset_class="EQUITY").results
    assert application.search(query="BTC").results[0].instrument.display_symbol == "BTCUSD"
    assert calls == ["discovery", "instruments"]


class CoupledDiscoveryFactory(Factory):
    def __init__(self) -> None:
        self.described = False

    def discovery_capabilities(self, config: object) -> OnlyDataSourceDiscoveryCapabilitiesV1:
        self.described = True
        return super().discovery_capabilities(config)

    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        assert self.described, "cold capabilities and catalogue must execute in one process"
        assert request.snapshot and request.query == "" and request.limit == 10001
        return (instrument("BTCUSD"),)


def test_cold_discovery_executes_capabilities_and_catalogue_in_same_child() -> None:
    # Assert the coupled callback lifecycle under the shipping eight-second
    # source budget; this is not a three-second cold-import performance gate.
    status, result = discovery._provider_call(
        CoupledDiscoveryFactory(),
        "discovery",
        OnlyDataSourceInstrumentCatalogRequestV1(None, query="BTC"),
        time.monotonic() + 8,
    )
    assert status == "COMPLETE"
    assert result == (Factory().discovery_capabilities(None), (instrument("BTCUSD"),))


def test_provider_worker_does_not_reexecute_service_main(tmp_path) -> None:
    import subprocess
    import sys
    from pathlib import Path

    marker = tmp_path / "service-starts.txt"
    launcher = tmp_path / "service.py"
    launcher.write_text(
        "from pathlib import Path\n"
        f"marker = Path({str(marker)!r})\n"
        "marker.write_text((marker.read_text() if marker.exists() else '') + 'startup\\n')\n"
        "if __name__ != '__main__':\n    raise RuntimeError('service main reexecuted')\n"
        "import sys, time\n"
        f"sys.path.insert(0, {str(Path.cwd())!r})\n"
        "from onlyalpha.application.market_data_discovery import _provider_call\n"
        "from onlyalpha.plugin.data_source import OnlyDataSourceInstrumentCatalogRequestV1\n"
        "from tests.application.test_market_data_discovery import RoundtripFactory\n"
        "status, result = _provider_call(RoundtripFactory(), 'instruments', "
        "OnlyDataSourceInstrumentCatalogRequestV1(None, query='BTC'), time.monotonic() + 8)\n"
        "assert status == 'COMPLETE', status\n"
        "assert result[0].display_symbol == 'BTCUSD'\n"
    )
    result = subprocess.run([sys.executable, str(launcher)], capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text() == "startup\n"


class NoisyFactory(RoundtripFactory):
    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        import os
        import sys

        print("provider log must not reach protocol stdout")
        sys.stdout.buffer.write(b"direct buffer output")
        os.write(1, b"direct descriptor output")
        return super().list_instruments(request)


def test_plugin_stdout_cannot_corrupt_protocol_response() -> None:
    status, result = discovery._provider_call(
        NoisyFactory(),
        "instruments",
        OnlyDataSourceInstrumentCatalogRequestV1(None, query="BTC"),
        time.monotonic() + 8,
    )
    assert status == "COMPLETE" and result == (instrument("BTCUSD"),)


def test_source_budget_covers_measured_compressed_catalogue_without_extending_overall_deadline(monkeypatch) -> None:
    observed = []
    monkeypatch.setattr(discovery.time, "monotonic", lambda: 100.0)

    def provider(factory, operation, request, deadline):
        observed.append((deadline, request.deadline_monotonic))
        return "COMPLETE", (Factory().discovery_capabilities(None), (instrument("BTCUSD"),))

    monkeypatch.setattr(discovery, "_provider_call", provider)
    application = service([runtime()])
    application._search_source(runtime(), "BTC", None, (), 25, 110.0)
    assert observed == [(108.0, 108.0)]
    observed.clear()
    application._search_source(runtime(replace(SELECTION, integration_id="second")), "BTC", None, (), 25, 103.0)
    assert observed == [(103.0, 103.0)]


def test_quote_source_uses_same_eight_second_budget(monkeypatch) -> None:
    monkeypatch.setattr(discovery.time, "monotonic", lambda: 100.0)

    def provider(factory, operation, request, deadline):
        assert operation == "quotes" and deadline == request.deadline_monotonic == 108.0
        return "COMPLETE", (OnlyDataSourceQuoteV1("BTCUSD.VENUE", "100", "1", "ROLLING_24H", 123),)

    monkeypatch.setattr(discovery, "_provider_call", provider)
    result = service([runtime()]).quotes(REFERENCE, instrument_ids=("BTCUSD.VENUE",))
    assert result.quotes[0].status == "AVAILABLE"
