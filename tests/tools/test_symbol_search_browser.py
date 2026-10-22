"""Controlled external payloads must cross the real provider-process boundary."""

import time

from onlyalpha.application.market_data_discovery import _provider_call
from onlyalpha.plugin.data_source import OnlyDataSourceInstrumentCatalogRequestV1, OnlyDataSourceQuoteRequestV1
from tests.runtime_support.binance_market_wire import _WatchlistWireFactory


def test_symbol_slice_uses_real_binance_parsers_inside_spawned_provider():
    factory = _WatchlistWireFactory(quotes_enabled=True)
    config = factory.parse_config({})
    status, instruments = _provider_call(
        factory,
        "instruments",
        OnlyDataSourceInstrumentCatalogRequestV1(config, query="BTC", limit=25),
        time.monotonic() + 6,
    )
    assert status == "COMPLETE"
    assert [str(item.instrument.instrument_id) for item in instruments] == ["BTCUSDT.BINANCE"]
    status, quotes = _provider_call(
        factory,
        "quotes",
        OnlyDataSourceQuoteRequestV1(config, ("BTCUSDT.BINANCE",), time.monotonic() + 6),
        time.monotonic() + 6,
    )
    assert status == "COMPLETE"
    assert quotes[0].last_price == "105.00"
    assert quotes[0].change_pct == "2.50"


def test_slice_inventory_allows_owning_changes_and_rejects_unrelated_truth():
    from copy import deepcopy

    import pytest

    from tests.support.browser_database import _assert_slice_inventory

    before = {
        "database": {
            "postgres:integration": {"count": 2},
            "postgres:watchlist_revision": {"count": 0},
            "postgres:market_data_revision": {"count": 0},
        },
        "files": {"research/semantic-store.json": "identity"},
    }
    after = deepcopy(before)
    after["database"]["postgres:watchlist_revision"]["count"] = 2
    after["database"]["postgres:market_data_revision"]["count"] = 1
    after["files"]["history/wal.json"] = "facts"
    _assert_slice_inventory(before, after)
    after["database"]["postgres:integration"]["count"] = 3
    with pytest.raises(AssertionError, match="postgres:integration"):
        _assert_slice_inventory(before, after)
    after["database"]["postgres:integration"]["count"] = 2
    after["files"]["research/semantic-store.json"] = "different identity"
    with pytest.raises(AssertionError):
        _assert_slice_inventory(before, after)


def test_read_only_fixture_factories_declare_search_but_never_quotes():
    from tests.application.test_market_data_product import _descriptor, _FakeFactory, _Faults, _ProviderCalls

    local_factory = _FakeFactory(_descriptor(), _ProviderCalls(), _Faults())
    local = local_factory.discovery_capabilities({})
    assert local.asset_classes == ("CRYPTOCURRENCY",)
    assert local.catalogue_snapshot is True
    assert local.quotes is False
    binance_factory = _WatchlistWireFactory()
    config = binance_factory.parse_config({})
    binance = binance_factory.discovery_capabilities(config)
    assert binance.catalogue_snapshot is True
    assert binance.quotes is False
    for factory, configuration, expected in (
        (local_factory, {}, "BTCUSDT.TEST"),
        (binance_factory, config, "BTCUSDT.BINANCE"),
    ):
        status, instruments = _provider_call(
            factory,
            "instruments",
            OnlyDataSourceInstrumentCatalogRequestV1(configuration, query="BTC", limit=25),
            time.monotonic() + 6,
        )
        assert status == "COMPLETE"
        assert [str(item.instrument.instrument_id) for item in instruments] == [expected]
        status, quotes = _provider_call(
            factory,
            "quotes",
            OnlyDataSourceQuoteRequestV1(configuration, (expected,), time.monotonic() + 6),
            time.monotonic() + 6,
        )
        assert status == "UNSUPPORTED"
        assert quotes == ()
    assert local_factory._provider.sessions == 0
    assert local_factory._provider.bar_fetches == 0


def test_local_read_browser_factory_is_spawn_safe_without_mutating_preconditions(tmp_path):
    from tests.application.test_market_data_product import _service
    from tests.runtime_support.local_read_provider import _ReadBrowserFactory

    harness = _service(tmp_path, factory_type=_ReadBrowserFactory)
    # Same lifecycle as Browser fixture: this setup-only observation is detached
    # before search; Provider subprocesses never receive Store/callback authority.
    harness.provider.canonical_writes = None
    before = harness.catalog.mutations
    status, instruments = _provider_call(
        harness.factory,
        "instruments",
        OnlyDataSourceInstrumentCatalogRequestV1({}, query="BTCUSDT", limit=25),
        time.monotonic() + 6,
    )
    assert status == "COMPLETE"
    assert [str(item.instrument.instrument_id) for item in instruments] == ["BTCUSDT.TEST"]
    assert harness.catalog.mutations == before
    assert harness.provider.bar_fetches == 0
    assert harness.provider.sessions == 0


def test_binance_wire_factory_import_is_lightweight_and_pickle_identity_is_stable():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import pickle
import sys
from tests.runtime_support.binance_market_wire import _WatchlistWireFactory
factory = _WatchlistWireFactory(quotes_enabled=True)
assert type(factory).__module__ == 'tests.runtime_support.binance_market_wire'
assert type(pickle.loads(pickle.dumps(factory))) is _WatchlistWireFactory
for name in sys.modules:
    assert not name.startswith(('onlyalpha_http_server', 'scripts.database',
        'tests.runtime_support.chart_study_browser', 'tests.runtime_support.local_read_browser')), name
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_local_read_provider_pickle_identity_is_stable_without_serving_app():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import pickle
import sys
from tests.runtime_support.local_read_provider import _ReadBrowserFactory
from tests.application.test_market_data_product import _descriptor, _ProviderCalls, _Faults
factory = _ReadBrowserFactory(_descriptor(), _ProviderCalls(), _Faults())
assert type(factory).__module__ == 'tests.runtime_support.local_read_provider'
assert type(pickle.loads(pickle.dumps(factory))) is _ReadBrowserFactory
assert not any(name.startswith('onlyalpha_http_server') for name in sys.modules)

""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
