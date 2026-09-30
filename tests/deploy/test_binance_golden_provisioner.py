from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyCurrencyType, OnlyMarketType, OnlySessionType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId, OnlyRawSymbol
from onlyalpha.domain.instrument import OnlyCryptoSpot
from onlyalpha.domain.market import OnlyBar, OnlyBarSemantic, OnlyBarType
from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.market_data.durable import (
    OnlyHistoricalMarketDataQueryService,
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
)


def _module():  # type: ignore[no-untyped-def]
    root = Path(__file__).parents[2]
    for relative in (
        "plugs/onlyalpha-plugin-binance/src",
        "plugs/onlyalpha-plugin-binance-spot/src",
        "plugs/onlyalpha-plugin-binance-usdm/src",
    ):
        sys.path.insert(0, str(root / relative))
    path = root / "scripts/provision_binance_golden.py"
    spec = importlib.util.spec_from_file_location("onlyalpha_binance_golden_provisioner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dataset_event_range_contains_final_closed_bar_event() -> None:
    module = _module()
    start = datetime(2026, 9, 2, 11, 48, tzinfo=UTC)
    end = datetime(2026, 9, 2, 11, 49, tzinfo=UTC)

    event_range = module._dataset_event_range(start, end)

    assert event_range.contains(end)
    assert not event_range.contains(event_range.end)


def test_physical_capture_sessions_are_unique_and_retain_authority() -> None:
    module = _module()

    first = module._capture_session_id("capture-sha256", "segment-1")
    second = module._capture_session_id("capture-sha256", "segment-2")

    assert first == "capture-sha256:segment-1"
    assert second == "capture-sha256:segment-2"
    assert first != second


def test_provisioner_initializes_product_output_roots(tmp_path: Path) -> None:
    module = _module()
    layout = module.OnlyUserDataLayout(tmp_path)

    module._ensure_product_roots(layout)

    assert layout.research_artifact_root.is_dir()
    assert layout.backtest_evidence_root.is_dir()


def test_offline_archive_client_projects_certified_rows_as_rest_pages() -> None:
    module = _module()
    client = module._ArchiveHttpClient(
        {
            ("SPOT_BAR", "BTCUSDT"): (
                ["1704067200000", "1", "2", "0.5", "1.5", "10", "1704067259999", "", "", "", "", ""],
                ["1704067260000", "1.5", "2", "1", "1.8", "11", "1704067319999", "", "", "", "", ""],
            ),
            ("USDM_FUNDING", "BTCUSDT"): (
                {"fundingTime": "1704067200000", "fundingRate": "0.0001", "symbol": "BTCUSDT"},
            ),
        },
        1704067320000,
    )

    bars = module._decode(
        client.get_json(
            "/api/v3/klines",
            {"symbol": "BTCUSDT", "startTime": "1704067260000", "endTime": "1704067320000", "limit": "1"},
        ),
        expected=list,
    )
    funding = module._decode(
        client.get_json("/fapi/v1/fundingRate", {"symbol": "BTCUSDT"}),
        expected=list,
    )

    assert [row[0] for row in bars] == ["1704067260000"]
    assert funding == [{"fundingRate": "0.0001", "fundingTime": "1704067200000", "symbol": "BTCUSDT"}]


def test_raw_pages_persist_through_recovery_before_wal_gc(tmp_path: Path) -> None:
    module = _module()
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    wal_root = tmp_path / "raw"

    module._persist_raw_pages(
        (module._Page("/raw", (), b"{}", (), 1),),
        source="BINANCE_USDM",
        capture_session="capture",
        market="USDM",
        stream="mark-price-1m",
        wal_root=wal_root,
        store=store,
        catalog=catalog,
    )

    assert len(catalog._segments) == 1
    assert len(catalog._physical_proofs) == 1
    assert catalog._revisions == {}
    assert OnlyMarketDataWal(wal_root, capacity_bytes=128 * 1024 * 1024).scan_uncommitted() == ()


def test_raw_pages_catalog_failure_keeps_wal_recoverable(tmp_path: Path) -> None:
    module = _module()
    store = OnlyInMemoryMarketFactStore()

    class _FailOnceCatalog(OnlyInMemoryMarketDataCatalog):
        commits = 0

        def commit_durable_segments(self, segments, proofs):  # type: ignore[no-untyped-def]
            self.commits += 1
            if self.commits == 1:
                raise RuntimeError("catalog unavailable")
            return super().commit_durable_segments(segments, proofs)

    catalog = _FailOnceCatalog()
    wal_root = tmp_path / "raw"
    with pytest.raises(RuntimeError, match="catalog unavailable"):
        module._persist_raw_pages(
            (module._Page("/raw", (), b"{}", (), 1),),
            source="BINANCE_USDM",
            capture_session="capture",
            market="USDM",
            stream="funding",
            wal_root=wal_root,
            store=store,
            catalog=catalog,
        )

    wal = OnlyMarketDataWal(wal_root, capacity_bytes=128 * 1024 * 1024)
    assert len(wal.scan_uncommitted()) == 1
    recovery = OnlyMarketDataRecoveryCoordinator(wal, store, catalog, OnlyRevisionCommitService(store, catalog))
    assert recovery.recover_all() == ("DURABLE_ONLY:RAW_ONLY",)
    assert catalog.commits == 2
    assert wal.scan_uncommitted() == ()


def test_bar_persistence_returns_exact_verified_revision(tmp_path: Path) -> None:
    module = _module()
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(minutes=1)
    instrument = OnlyCryptoSpot(
        instrument_id=OnlyInstrumentId.parse("BTCUSDT.BINANCE"),
        raw_symbol=OnlyRawSymbol("BTCUSDT"),
        market_type=OnlyMarketType.CASH,
        quote_currency=OnlyCurrency("USDT", 8, OnlyCurrencyType.CRYPTO),
        settlement_currency=OnlyCurrency("USDT", 8, OnlyCurrencyType.CRYPTO),
        base_currency=OnlyCurrency("BTC", 8, OnlyCurrencyType.CRYPTO),
        price_precision=2,
        quantity_precision=3,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("0.001"), 3),
        minimum_quantity=OnlyQuantity(Decimal("0.001"), 3),
        maximum_quantity=None,
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        trading_calendar_id=OnlyCalendarId("BINANCE-24X7"),
    )
    bar = OnlyBar(
        bar_type=OnlyBarType(instrument.instrument_id, OnlyBarSemantic.fixed_duration(1)),
        open=OnlyPrice(Decimal("100.00"), 2),
        high=OnlyPrice(Decimal("101.00"), 2),
        low=OnlyPrice(Decimal("99.00"), 2),
        close=OnlyPrice(Decimal("100.50"), 2),
        volume=OnlyQuantity(Decimal("10.000"), 3),
        quote_volume=None,
        turnover=None,
        trade_count=1,
        open_interest=None,
        bar_start=start,
        bar_end=end,
        ts_event=end,
        ts_init=end,
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=date(2026, 1, 1),
        session_type=OnlySessionType.CONTINUOUS,
    )
    source = OnlyMarketDataSourceId("BINANCE_SPOT")
    version = OnlyDataVersion("BINANCE_SPOT_REST_V1")
    page = module._Page("/api/v3/klines", (), b"[]", (), int(end.timestamp() * 1_000_000_000))

    revision_id, scope = module._persist_bars(
        pages=(page,),
        page_updates=((module._bar_update(bar, source, version),),),
        instrument=instrument,
        source=source,
        version=version,
        market="SPOT",
        capture_session="a" * 64,
        start=start,
        end=end,
        wal_root=tmp_path / "bars",
        store=store,
        catalog=catalog,
    )

    revision = OnlyHistoricalMarketDataQueryService(catalog, store).resolve_latest(scope)
    facts = OnlyHistoricalMarketDataQueryService(catalog, store).read_exact(revision_id, scope)
    manifest = catalog.load_coverage_manifest(revision.manifest_id)
    assert revision.revision_id == revision_id
    assert len(facts) == 1
    assert manifest.coverage_status.value == "COMPLETE"
