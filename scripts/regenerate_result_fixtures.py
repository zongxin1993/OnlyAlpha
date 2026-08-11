from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onlyalpha.config import OnlyClusterCapitalConfig, OnlyClusterCapitalMode, OnlyClusterRunConfig  # noqa: E402
from onlyalpha.domain.identifiers import OnlyEngineId  # noqa: E402
from onlyalpha.domain.value import OnlyMoney  # noqa: E402
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig  # noqa: E402
from onlyalpha.result import only_backtest_business_projection, only_result_fingerprint  # noqa: E402
from tests.integration.test_engine_multi_cluster_close_cost_authority import _configs  # noqa: E402
from tests.integration.virtual_multi_fill_support import only_virtual_multi_fill_config  # noqa: E402
from tests.support.canonical import canonical_value, write_canonical_json  # noqa: E402

TARGET = ROOT / "tests" / "fixtures" / "results"
SCENARIOS = ("minimal_round_trip", "multi_fill_round_trip", "multi_cluster_close")


def _minimal_config() -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load(ROOT / "tests" / "fixtures" / "legacy_macd" / "cluster_fast.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    payload["runtime"]["start_time"] = start.isoformat().replace("+00:00", "Z")
    payload["runtime"]["end_time"] = (start + timedelta(minutes=8)).isoformat().replace("+00:00", "Z")
    payload["strategy"]["class_path"] = "tests.integration.virtual_multi_fill_support:OnlyRoundTripLongCloseStrategy"
    payload["factors"][0]["indicators"][0]["parameters"] = {
        "fast_period": 2,
        "slow_period": 3,
        "signal_period": 1,
        "warmup_bars": 3,
    }
    payload["data_sources"] = [
        {
            "source_id": "result-fixture-exact",
            "plugin": "scenario-exact",
            "data_version": "result-fixture-v1",
            "batch_size": 16,
            "coverage": {"universe_ids": ["macd-demo-universe"]},
            "extensions": {
                "bars": [
                    {
                        "instrument_id": "TESTETF.XSHG",
                        "ts_event_ns": int((start + timedelta(minutes=index)).timestamp() * 1_000_000_000),
                        "ts_init_ns": int((start + timedelta(minutes=index)).timestamp() * 1_000_000_000),
                        "sequence": index,
                        "open": f"{10 + index / 100:.2f}",
                        "high": f"{10.1 + index / 100:.2f}",
                        "low": f"{9.9 + index / 100:.2f}",
                        "close": f"{10.05 + index / 100:.2f}",
                        "volume": "10000",
                    }
                    for index in range(1, 8)
                ]
            },
        }
    ]
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def _scenario_configs(name: str) -> tuple[OnlyClusterRunConfig, ...]:
    if name == "minimal_round_trip":
        return (_minimal_config(),)
    if name == "multi_fill_round_trip":
        return (only_virtual_multi_fill_config(long_close=True),)
    if name == "multi_cluster_close":
        configs = _configs()
        currency = configs[0].accounts[0].initial_cash.currency
        capital = OnlyClusterCapitalConfig(
            OnlyClusterCapitalMode.FIXED_CAPITAL,
            OnlyMoney(Decimal("500000.00"), currency),
        )
        return tuple(replace(item, cluster=replace(item.cluster, capital=capital)) for item in configs)
    raise ValueError(f"unknown result fixture scenario: {name}")


def regenerate(name: str, generated_at: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"onlyalpha-{name}-") as raw:
        run_root = Path(raw)
        engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId(f"fixture-{name}"), run_root))
        configs = _scenario_configs(name)
        for config in configs:
            engine.add_cluster(config)
        result = engine.run()
        if result.status != "COMPLETED" or not result.runtime_results:
            raise RuntimeError(f"fixture generation failed for {name}: {result.failures}")
        runtime_result = result.runtime_results[0]
        projection = canonical_value(only_backtest_business_projection(runtime_result))
        facts = runtime_result.facts
        if facts.market_product is None:
            raise RuntimeError(f"fixture generation lacks Market Product evidence for {name}")
        target = TARGET / name
        staging = TARGET / f".{name}.staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        write_canonical_json(staging / "result.json", result.to_dict())
        write_canonical_json(staging / "canonical_projection.json", projection)
        manifest = {
            "fixture_schema_version": 2,
            "onlyalpha_version": "0.3.6",
            "scenario": name,
            "generation_command": f"uv run python scripts/regenerate_result_fixtures.py --scenario {name}",
            "market_products": [
                {
                    "provider_plugin_id": str(config.market.plugin_id),
                    "product_id": str(config.market.product_id),
                    "product_version": str(config.market.product_version),
                }
                for config in configs
            ],
            "market_product_evidence": canonical_value(facts.market_product),
            "runtime_type": "BACKTEST",
            "data_fingerprint": only_result_fingerprint(runtime_result.data),
            "configuration_fingerprint": result.determinism_fingerprint,
            "result_fingerprint": runtime_result.result_fingerprint,
            "generated_at": generated_at,
            "expected_trade_count": len(runtime_result.trades),
            "expected_fill_count": len(facts.executions),
            "expected_terminal_count": sum(
                item.status in {"CANCELLED", "REJECTED", "EXPIRED"} for item in facts.orders
            ),
        }
        write_canonical_json(staging / "manifest.json", manifest)
        if target.exists():
            shutil.rmtree(target)
        staging.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate immutable results from formal OnlyEngine runs")
    parser.add_argument("--scenario", action="append", choices=SCENARIOS)
    parser.add_argument("--generated-at", default="2026-08-08T00:00:00Z")
    args = parser.parse_args()
    for scenario in args.scenario or SCENARIOS:
        regenerate(scenario, args.generated_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
