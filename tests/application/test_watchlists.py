from dataclasses import replace

import pytest

from onlyalpha.application.market_data_product import OnlyMarketDataSourceReferenceV1
from onlyalpha.application.watchlists import OnlyWatchlist, OnlyWatchlistError, OnlyWatchlistMember

SOURCE = OnlyMarketDataSourceReferenceV1("source", "a" * 64, "test.market_data")


def test_mixed_sources_preserve_exact_member_identity():
    first = OnlyWatchlistMember(SOURCE, "BTCUSDT.BINANCE")
    second = OnlyWatchlistMember(replace(SOURCE, integration_revision_fingerprint="b" * 64), first.instrument_id)
    item = OnlyWatchlist("0926c6a2-0cb8-47a5-8d94-cdb89b336182", "日常", (first, second))
    assert item.members == (first, second)
    with pytest.raises(OnlyWatchlistError, match="WATCHLIST_INVALID"):
        replace(item, members=(first, first))


def test_new_members_are_validated_by_exact_source_and_existing_unavailable_members_retained():
    from onlyalpha.application.watchlists import OnlyWatchlistBook, OnlyWatchlistService

    first = OnlyWatchlistMember(SOURCE, "BTCUSDT.BINANCE")
    other = OnlyWatchlistMember(replace(SOURCE, integration_id="other"), first.instrument_id)
    item = OnlyWatchlist("0926c6a2-0cb8-47a5-8d94-cdb89b336182", "日常", (first,))

    class Store:
        def command(self, _command):
            return None

        def read(self):
            return OnlyWatchlistBook(1, (item,))

        def save(self, _command, version, lists):
            return OnlyWatchlistBook(version + 1, lists)

    class Market:
        def __init__(self):
            self.seen = []

        def list_instruments(self, source, *, instrument_ids, **_kwargs):
            self.seen.append(source)
            assert source == other.source
            assert instrument_ids == (other.instrument_id,)

    class Session:
        def check_active(self):
            pass

    market = Market()
    service = OnlyWatchlistService(Store(), market)
    result = service.save(
        "85e1e338-081d-4e32-8bf8-86c79f162a3d", 1, (replace(item, name="修改", members=(first, other)),), Session()
    )
    assert result.lists[0].members == (first, other)
    assert market.seen == [other.source]
    market.seen.clear()
    service.save("ee9df22c-b522-42b8-9693-97c779027acf", 1, (replace(item, name="保留"),), Session())
    assert market.seen == []


def test_historical_reader_verifies_original_identity_before_projection():
    from dataclasses import asdict

    from onlyalpha.canonical import only_canonical_fingerprint
    from onlyalpha.persistence.postgres.watchlist_store import OnlyPostgresWatchlistStore
    from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreId

    namespace = OnlyResearchSemanticStoreId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
    store = OnlyPostgresWatchlistStore("postgresql://localhost/onlyalpha_test", namespace)
    payload = {
        "version": 1,
        "lists": [
            {
                "list_id": "0926c6a2-0cb8-47a5-8d94-cdb89b336182",
                "name": "日常",
                "source": asdict(SOURCE),
                "instrument_ids": ["BTCUSDT.BINANCE"],
            }
        ],
    }
    fingerprint = only_canonical_fingerprint({"namespace_id": namespace.value, "book": payload})
    projected = store._read_revision((1, fingerprint, payload, 1))
    assert projected.lists[0].members == (OnlyWatchlistMember(SOURCE, "BTCUSDT.BINANCE"),)
    assert store._historical_intent(0, projected.lists) == only_canonical_fingerprint(
        {"namespace_id": namespace.value, "expected_version": 0, "lists": payload["lists"]}
    )
    with pytest.raises(OnlyWatchlistError, match="HISTORY_CORRUPT"):
        store._read_revision((1, fingerprint, payload, 2))
    payload["lists"][0]["source"]["integration_id"] = "other"
    with pytest.raises(OnlyWatchlistError, match="HISTORY_CORRUPT"):
        store._read_revision((1, fingerprint, payload, 1))


def test_new_source_validation_failure_cannot_persist_an_edit():
    from onlyalpha.application.market_data_product import OnlyMarketDataProductError
    from onlyalpha.application.watchlists import OnlyWatchlistBook, OnlyWatchlistService

    original = OnlyWatchlistBook(
        1,
        (
            OnlyWatchlist(
                "0926c6a2-0cb8-47a5-8d94-cdb89b336182", "日常", (OnlyWatchlistMember(SOURCE, "BTCUSDT.BINANCE"),)
            ),
        ),
    )

    class Store:
        book = original

        def command(self, _command):
            return None

        def read(self):
            return self.book

        def save(self, _command, version, lists):
            self.book = OnlyWatchlistBook(version + 1, lists)
            return self.book

    class Market:
        def list_instruments(self, source, **_kwargs):
            assert source.integration_id == "unavailable"
            raise OnlyMarketDataProductError("MARKET_DATA_REFERENCE_UNAVAILABLE")

    class Session:
        def check_active(self):
            pass

    store = Store()
    service = OnlyWatchlistService(store, Market())
    member = OnlyWatchlistMember(replace(SOURCE, integration_id="unavailable"), "BTCUSDT.BINANCE")
    changed = replace(original.lists[0], members=(*original.lists[0].members, member))
    with pytest.raises(OnlyMarketDataProductError, match="MARKET_DATA_REFERENCE_UNAVAILABLE"):
        service.save("b044bafe-f185-47d0-8132-23878c70687a", 1, (changed,), Session())
    assert store.read() == original
