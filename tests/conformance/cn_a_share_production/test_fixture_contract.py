from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from collections.abc import Iterator, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from onlyalpha_plugin_cn_ashare.factory import OnlyCnAshareMarketProductFactory
from onlyalpha_plugin_cn_ashare.fee_pack import (
    CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM,
    only_cn_a_share_market_fee_pack,
)
from onlyalpha_plugin_cn_ashare.fee_pack import (
    PACK_ID as CN_A_SHARE_PRODUCTION_MARKET_FEE_PACK_ID,
)
from onlyalpha_plugin_cn_ashare.fee_pack import (
    PACK_VERSION as CN_A_SHARE_PRODUCTION_MARKET_FEE_PACK_VERSION,
)
from onlyalpha_plugin_cn_ashare.reference import (
    OnlyCnAshareInstrumentReference,
    OnlyCnAshareReferenceAuthority,
    OnlyCnAshareReferenceSource,
    OnlyCnAshareSecurityType,
)

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.execution import ONLY_READABLE_EXECUTION_SUPPORT_POLICY_VERSIONS
from onlyalpha.fee import OnlyBrokerFeeContractDocumentLoader
from onlyalpha.fee.schedules import OnlyMarketFeeApplicabilityContext
from onlyalpha.market.product import (
    OnlyCanonicalMarketProductConfig,
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
)
from tests.conformance.cn_a_share_production.support import (
    ACCOUNT_ID,
    BROKER_FEE_CONTRACT_ID,
    BROKER_FEE_CONTRACT_VERSION,
    only_cn_a_share_product_broker_fee_contract,
)
from tests.runtime_support.market_product import _NoResources

pytestmark = pytest.mark.conformance

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "tests" / "fixtures" / "conformance" / "cn_a_share_production_v1"
DATA_FILES = frozenset({"bars.json", "references.json"})
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object with string keys")
    return cast(dict[str, object], value)


def _objects(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return [_object(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be non-empty text")
    return value


def _text_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be an array of non-empty text")
    return cast(list[str], value)


def _read_object(path: Path) -> dict[str, object]:
    return _object(json.loads(path.read_text(encoding="utf-8")), str(path))


def _read_objects(path: Path) -> list[dict[str, object]]:
    return _objects(json.loads(path.read_text(encoding="utf-8")), str(path))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _content_fingerprint(manifest: Mapping[str, object]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "content_fingerprint"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_sealed_fixture(root: Path) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    manifest = _read_object(root / "manifest.json")
    files = _object(manifest.get("files"), "manifest.files")
    if set(files) != DATA_FILES:
        raise ValueError("manifest.files must name exactly the frozen local data files")
    for relative_path, expected in files.items():
        if Path(relative_path).name != relative_path:
            raise ValueError("manifest file paths must be local basenames")
        fingerprint = _text(expected, f"manifest.files.{relative_path}")
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise ValueError(f"manifest.files.{relative_path} must be lowercase SHA-256")
        if _file_sha256(root / relative_path) != fingerprint:
            raise ValueError(f"{relative_path} SHA-256 mismatch")
    expected_content = _text(manifest.get("content_fingerprint"), "manifest.content_fingerprint")
    if _content_fingerprint(manifest) != expected_content:
        raise ValueError("manifest content fingerprint mismatch")
    bars = _read_objects(root / "bars.json")
    references = _read_objects(root / "references.json")
    return manifest, bars, references


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from _strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _strings(nested)


def _bar_trading_day(raw: Mapping[str, object]) -> date:
    timestamp = datetime.fromisoformat(_text(raw.get("ts_event"), "bar.ts_event").replace("Z", "+00:00"))
    if timestamp.utcoffset() is None:
        raise ValueError("bar.ts_event must include an explicit UTC offset")
    return timestamp.astimezone(SHANGHAI).date()


def test_fixture_is_frozen_local_synthetic_data_without_fallback() -> None:
    manifest, bars, references = _load_sealed_fixture(DATASET)

    assert {path.name for path in DATASET.iterdir()} == {"manifest.json", *DATA_FILES}
    assert manifest["schema_version"] == 1
    assert manifest["dataset_id"] == "CN_A_SHARE_PRODUCTION_V1_SYNTHETIC_BARS"
    assert manifest["product_id"] == "CN_A_SHARE_DURABLE_BACKTEST_V1"
    assert manifest["product_contract_version"] == "1"
    assert manifest["source"] == "OnlyAlpha deterministic synthetic market-data fixture"
    assert manifest["source_kind"] == "SYNTHETIC_MARKET_DATA_FIXTURE"
    assert manifest["source_version"] == "1"
    assert manifest["data_version"] == "cn-a-share-production-v1-synthetic-bars-v1"
    assert manifest["synthetic_market_data_fixture"] is True
    assert manifest["runtime_policy"] == {
        "data_access": "FROZEN_LOCAL_ONLY",
        "network_access": "FORBIDDEN",
        "implicit_fallback": "FORBIDDEN",
    }
    assert manifest["record_counts"] == {"bars.json": len(bars), "references.json": len(references)}
    assert not any("://" in value for value in _strings(manifest))
    assert "CN_A_SHARE_TEST_MARKET_FEE_PACK" not in json.dumps(manifest, sort_keys=True)


@pytest.mark.parametrize(
    ("filename", "original", "replacement"),
    (
        ("bars.json", '"close":"10.00"', '"close":"10.01"'),
        ("references.json", '"previous_close": "10.00"', '"previous_close": "10.01"'),
    ),
)
def test_data_file_tampering_is_rejected(tmp_path: Path, filename: str, original: str, replacement: str) -> None:
    copied = tmp_path / "dataset"
    shutil.copytree(DATASET, copied)
    target = copied / filename
    payload = target.read_text(encoding="utf-8")
    assert original in payload
    target.write_text(payload.replace(original, replacement, 1), encoding="utf-8")

    with pytest.raises(ValueError, match=rf"{filename} SHA-256 mismatch"):
        _load_sealed_fixture(copied)


def test_manifest_tampering_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "dataset"
    shutil.copytree(DATASET, copied)
    manifest_path = copied / "manifest.json"
    manifest = _read_object(manifest_path)
    manifest["data_version"] = "tampered-version"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest content fingerprint mismatch"):
        _load_sealed_fixture(copied)


def test_trading_dates_resolve_current_production_product_and_fee_authority() -> None:
    manifest, bars, _ = _load_sealed_fixture(DATASET)
    coverage = _object(manifest.get("coverage"), "manifest.coverage")
    authority = _object(manifest.get("production_fee_authority"), "manifest.production_fee_authority")
    trading_days = tuple(date.fromisoformat(value) for value in _text_list(manifest.get("trading_dates"), "dates"))
    identities = _objects(manifest.get("instrument_identities"), "manifest.instrument_identities")

    pack = only_cn_a_share_market_fee_pack()
    assert authority == {
        "pack_id": CN_A_SHARE_PRODUCTION_MARKET_FEE_PACK_ID,
        "pack_version": CN_A_SHARE_PRODUCTION_MARKET_FEE_PACK_VERSION,
        "pack_fingerprint": pack.fingerprint,
        "coverage_from": CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM.isoformat(),
    }
    assert manifest["production_fee_coverage_from"] == CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM.isoformat()
    assert min(trading_days) >= CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM
    assert {_bar_trading_day(raw) for raw in bars} == set(trading_days)

    _, _, reference_values = _load_sealed_fixture(DATASET)
    binding = OnlyCnAshareMarketProductFactory().resolve(
        OnlyMarketProductConfig(
            OnlyMarketProductPluginId("onlyalpha-plugin-cn-ashare"),
            OnlyMarketProductId("CN_A_SHARE_CASH"),
            OnlyMarketProductVersion("2025.1"),
            OnlyCanonicalMarketProductConfig({"references": reference_values}),  # type: ignore[arg-type]
        ),
        OnlyMarketProductResolutionContext(_NoResources()),
    )
    for trading_day in trading_days:
        assert coverage["market_product"] == str(binding.product_identity.product_id)
        assert coverage["market_product_version"] == str(binding.product_identity.product_version)
        assert coverage["composition_fingerprint"] == binding.composition_identity.fingerprint
        for identity in identities:
            instrument_id = OnlyInstrumentId.parse(_text(identity.get("instrument_id"), "instrument_id"))
            venue = _text(identity.get("venue"), "venue")
            context = OnlyMarketFeeApplicabilityContext(
                OnlyTradingDay(trading_day),
                str(binding.product_identity.product_id),
                "CN_A_SHARE",
                venue,
                "CASH",
                instrument_id,
            )
            schedule_prefix = "CN_A_SHARE_SSE" if venue == "XSHG" else "CN_A_SHARE_SZSE"
            assert {schedule.schedule_id for schedule in pack.schedules if schedule.matches(context)} == {
                f"{schedule_prefix}_STAMP_DUTY",
                f"{schedule_prefix}_TRANSFER_FEE",
            }


def test_manifest_binds_independent_broker_execution_and_supported_surface_authorities() -> None:
    manifest, _, _ = _load_sealed_fixture(DATASET)
    broker = _object(manifest.get("broker_fee_authority"), "manifest.broker_fee_authority")
    execution = _object(
        manifest.get("execution_support_authority"),
        "manifest.execution_support_authority",
    )
    surface = _object(manifest.get("supported_surface"), "manifest.supported_surface")

    contract = OnlyBrokerFeeContractDocumentLoader.load(only_cn_a_share_product_broker_fee_contract())
    assert broker == {
        "contract_id": BROKER_FEE_CONTRACT_ID,
        "contract_version": BROKER_FEE_CONTRACT_VERSION,
        "contract_fingerprint": contract.fingerprint,
        "broker_id": "virtual",
        "account_id": ACCOUNT_ID,
        "currency": "CNY",
        "effective_from": "2025-01-01",
        "calculation_scope": "ORDER_CUMULATIVE",
        "commission_rate": "0.0003",
        "minimum_commission": "5.00",
    }
    assert execution == {
        "policy_version": "2",
        "capabilities": ["DURABLE_ORDER_ACCEPTED", "DURABLE_TRADE", "DURABLE_TERMINAL"],
        "market_identity_is_permission": False,
    }
    assert execution["policy_version"] in ONLY_READABLE_EXECUTION_SUPPORT_POLICY_VERSIONS
    assert surface == {
        "runtime": "BACKTEST",
        "currency": "CNY",
        "venues": ["XSHG", "XSHE"],
        "security_type": "COMMON_STOCK",
        "account_type": "CASH",
        "position_side": "LONG",
        "position_mode": "NETTING",
        "order_type": "LIMIT",
        "order_semantics": ["BUY_OPEN", "SELL_CLOSE"],
        "broker_lifecycle": ["ACCEPTED", "TRADE", "CANCELLED", "REJECTED", "EXPIRED"],
        "fills": ["WHOLE", "PARTIAL", "MULTI_FILL"],
        "settlement": "ORDINARY_T_PLUS_ONE_SELLABILITY",
        "persistence": ["MEMORY", "SQLITE"],
        "recovery": ["CHECKPOINT", "RESTART", "FORWARD_RECOVERY"],
        "output": ["DETERMINISTIC_RESULT", "DETERMINISTIC_ARTIFACT"],
    }


def test_xshg_xshe_bars_and_daily_references_are_complete_and_fingerprinted() -> None:
    manifest, bars, raw_references = _load_sealed_fixture(DATASET)
    coverage = _object(manifest.get("coverage"), "manifest.coverage")
    identities = _objects(manifest.get("instrument_identities"), "manifest.instrument_identities")
    calendars = _objects(manifest.get("trading_calendars"), "manifest.trading_calendars")
    authority = _object(manifest.get("reference_authority"), "manifest.reference_authority")
    trading_days = tuple(date.fromisoformat(value) for value in _text_list(manifest.get("trading_dates"), "dates"))
    instrument_ids = _text_list(manifest.get("instrument_ids"), "manifest.instrument_ids")

    assert set(instrument_ids) == {"600000.XSHG", "000001.XSHE"}
    assert coverage["currency"] == "CNY"
    assert coverage["security_type"] == "COMMON_STOCK"
    assert set(_text_list(coverage.get("venues"), "coverage.venues")) == {"XSHG", "XSHE"}
    assert {calendar["calendar_id"]: (calendar["venue"], calendar["timezone"]) for calendar in calendars} == {
        "CN_XSHG": ("XSHG", "Asia/Shanghai"),
        "CN_XSHE": ("XSHE", "Asia/Shanghai"),
    }
    assert set(_text_list(manifest.get("trading_calendar_ids"), "trading_calendar_ids")) == {
        "CN_XSHG",
        "CN_XSHE",
    }

    identity_by_instrument = {_text(item.get("instrument_id"), "identity.instrument_id"): item for item in identities}
    assert set(identity_by_instrument) == set(instrument_ids)
    assert identity_by_instrument["600000.XSHG"] == {
        "instrument_id": "600000.XSHG",
        "venue": "XSHG",
        "exchange": "SSE",
        "security_type": "COMMON_STOCK",
        "board": "SSE_MAIN",
        "trading_calendar_id": "CN_XSHG",
    }
    assert identity_by_instrument["000001.XSHE"] == {
        "instrument_id": "000001.XSHE",
        "venue": "XSHE",
        "exchange": "SZSE",
        "security_type": "COMMON_STOCK",
        "board": "SZSE_MAIN",
        "trading_calendar_id": "CN_XSHE",
    }

    records = tuple(OnlyCnAshareInstrumentReference.from_mapping(raw) for raw in raw_references)
    reference_authority = OnlyCnAshareReferenceAuthority.create(records)
    assert authority == {
        "model": "OnlyCnAshareInstrumentReference",
        "source": "SCENARIO",
        "source_version": "cn-a-share-production-v1-reference-v1",
        "data_version": "cn-a-share-production-v1-reference-v1",
        "bar_derivation": "FORBIDDEN",
        "authority_fingerprint": reference_authority.identity.authority_fingerprint,
    }
    expected_pairs = {(instrument_id, trading_day) for instrument_id in instrument_ids for trading_day in trading_days}
    assert {(str(record.instrument_id), record.effective_from) for record in records} == expected_pairs
    for raw, record in zip(raw_references, records, strict=True):
        assert raw["record_fingerprint"] == record.content_fingerprint
        assert record.security_type is OnlyCnAshareSecurityType.COMMON_STOCK
        assert record.source is OnlyCnAshareReferenceSource.SCENARIO
        assert record.effective_to is not None
        assert record.effective_to == record.effective_from + timedelta(days=1)
        identity = identity_by_instrument[str(record.instrument_id)]
        assert record.exchange.value == identity["exchange"]
        assert record.board.value == identity["board"]

    bars_by_instrument: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw in bars:
        instrument_id = _text(raw.get("instrument_id"), "bar.instrument_id")
        assert instrument_id in identity_by_instrument
        sequence = raw.get("sequence")
        assert isinstance(sequence, int)
        assert sequence > 0
        prices = tuple(Decimal(_text(raw.get(field), f"bar.{field}")) for field in ("open", "high", "low", "close"))
        assert prices[1] >= max(prices[0], prices[3])
        assert prices[2] <= min(prices[0], prices[3])
        assert Decimal(_text(raw.get("volume"), "bar.volume")) > 0
        trading_day = _bar_trading_day(raw)
        assert trading_day in trading_days
        reference_authority.resolve(OnlyInstrumentId.parse(instrument_id), OnlyTradingDay(trading_day))
        bars_by_instrument[instrument_id].append(raw)

    assert set(bars_by_instrument) == set(instrument_ids)
    for instrument_id, instrument_bars in bars_by_instrument.items():
        assert [item["sequence"] for item in instrument_bars] == list(range(1, 17)), instrument_id
        timestamps = [_text(item.get("ts_event"), "bar.ts_event") for item in instrument_bars]
        assert timestamps == sorted(timestamps)
        assert len(timestamps) == len(set(timestamps))
        assert {
            trading_day: sum(_bar_trading_day(item) == trading_day for item in instrument_bars)
            for trading_day in trading_days
        } == {trading_day: 8 for trading_day in trading_days}
