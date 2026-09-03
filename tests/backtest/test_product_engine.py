from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from onlyalpha.backtest import (
    OnlyBacktestAdmissionResolution,
    OnlyBacktestDeploymentCatalog,
    OnlyBacktestMarketProductResourceRegistry,
    OnlyBacktestProductEnginePlanBuilder,
    OnlyBacktestProfileReference,
    OnlyBacktestRun,
    OnlyBacktestRunId,
    OnlyBacktestSpecification,
    OnlyEngineBacktestRuntimeExecutor,
    only_default_backtest_profile_registry,
    only_load_backtest_deployment_catalog,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.strategy import OnlyFrozenStrategyRevisionStore
from tests.research.calculation.support import bars
from tests.strategy.p9_support import p9_strategy_case, publish_frozen_strategy_for_execution_test


def _deployment(case) -> OnlyClusterRunConfig:  # type: ignore[no-untyped-def]
    payload = json.loads(Path("tests/fixtures/legacy_macd/cluster.json").read_text(encoding="utf-8"))
    payload["runtime"].update(
        {
            "start_time": case.bars[0].bar_start.isoformat(),
            "end_time": case.dataset_store.load_verified_table(
                case.dataset_fingerprint
            ).snapshot.definition.time_range.end.isoformat(),
            "base_currency": "USD",
        }
    )
    payload["reference_data"] = {
        "calendars": [
            {
                "calendar_id": "XNAS",
                "venue": "XNAS",
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
            }
        ],
        "instruments": [
            {
                "instrument_id": str(instrument_id),
                "asset_class": "EQUITY",
                "timezone": "UTC",
                "trading_calendar_id": "XNAS",
                "price_precision": 2,
                "quantity_precision": 0,
                "price_increment": "0.01",
                "quantity_increment": "1",
                "lot_size": "1",
                "minimum_quantity": "1",
                "maximum_quantity": "100000000",
            }
            for instrument_id in case.revision.universe.instruments
        ],
    }
    payload["universes"] = [
        {
            "universe_id": "product-universe",
            "type": "STATIC",
            "instruments": [str(item) for item in case.revision.universe.instruments],
        }
    ]
    payload["data_sources"][0]["coverage"] = {"universe_ids": ["product-universe"]}
    payload["factors"] = []
    payload["accounts"][0]["initial_cash"] = {"value": "100000.00", "currency": "USD"}
    return OnlyClusterRunConfig.from_mapping(payload, source_path="<product-engine-test>")


def _run(case, document: OnlyClusterRunConfig, run_id: str) -> OnlyBacktestRun:  # type: ignore[no-untyped-def]
    profiles = only_default_backtest_profile_registry()
    portfolio = OnlyBacktestProfileReference("fixed-capital", "1")
    risk = OnlyBacktestProfileReference("default-risk", "1")
    execution = OnlyBacktestProfileReference("virtual-next-bar", "1")
    configuration = OnlyBacktestDeploymentCatalog((document,)).configuration_fingerprints[0]
    specification = OnlyBacktestSpecification(
        str(case.revision.strategy_fingerprint),
        "b" * 64,
        configuration,
        portfolio,
        risk,
        execution,
        "USD",
        "100000.00",
    )
    resolution = OnlyBacktestAdmissionResolution(
        1,
        str(case.revision.strategy_fingerprint),
        "b" * 64,
        case.dataset_fingerprint,
        "c" * 64,
        profiles.resolve_profile("PORTFOLIO", portfolio).fingerprint,
        profiles.resolve_profile("RISK", risk).fingerprint,
        profiles.resolve_profile("EXECUTION", execution).fingerprint,
        "ONLYALPHA_KERNEL_SEMANTICS@1",
        ("d" * 64,),
    )
    return OnlyBacktestRun.queued(
        run_id=OnlyBacktestRunId(run_id),
        specification=specification,
        admission_resolution=resolution,
        queued_at=datetime(2026, 9, 2, tzinfo=UTC),
    )


def test_operator_deployment_catalog_loads_exact_json_document(tmp_path) -> None:  # type: ignore[no-untyped-def]
    values = tuple(item for item in bars() if str(item.instrument_id) == "A.XNAS")
    case = p9_strategy_case(tmp_path / "case", values=values)
    document = _deployment(case)
    path = tmp_path / "product.json"
    path.write_text(only_canonical_json(document.normalized_payload), encoding="utf-8")

    loaded = only_load_backtest_deployment_catalog((path,))

    resource = loaded.document(loaded.configuration_fingerprints[0])
    assert dict(resource.market) == document.normalized_payload["market"]
    assert dict(resource.reference_data) == document.normalized_payload["reference_data"]


def test_operator_execution_mutation_does_not_enter_product_resource_semantics(tmp_path) -> None:  # type: ignore[no-untyped-def]
    values = tuple(item for item in bars() if str(item.instrument_id) == "A.XNAS")
    case = p9_strategy_case(tmp_path / "case", values=values)
    original = _deployment(case)
    changed_payload = json.loads(only_canonical_json(original.normalized_payload))
    changed_payload["brokers"][0]["extensions"] = {
        "matching": {"type": "MUTABLE_OPERATOR_VALUE"},
        "slippage": {"type": "MUTABLE_OPERATOR_VALUE"},
    }
    changed_payload["accounts"][0]["initial_cash"]["value"] = "999999999.99"
    changed = OnlyClusterRunConfig.from_mapping(changed_payload, source_path="<operational-mutation>")

    original_catalog = OnlyBacktestDeploymentCatalog((original,))
    changed_catalog = OnlyBacktestDeploymentCatalog((changed,))

    assert original_catalog.document(original_catalog.configuration_fingerprints[0]) == changed_catalog.document(
        changed_catalog.configuration_fingerprints[0]
    )


def test_product_plan_runs_existing_engine_and_distinct_runs_replay_identically(tmp_path) -> None:  # type: ignore[no-untyped-def]
    values = tuple(item for item in bars() if str(item.instrument_id) == "A.XNAS")
    case = p9_strategy_case(tmp_path / "case", values=values)
    semantic_root = tmp_path / "engine" / "research"
    publish_frozen_strategy_for_execution_test(semantic_root, case.revision)
    document = _deployment(case)
    catalog = OnlyBacktestDeploymentCatalog((document,))
    resources = OnlyBacktestMarketProductResourceRegistry()
    builder = OnlyBacktestProductEnginePlanBuilder(
        user_data_root=tmp_path / "engine",
        catalog=catalog,
        strategies=OnlyFrozenStrategyRevisionStore(semantic_root),
        datasets=case.dataset_store,
        profiles=only_default_backtest_profile_registry(),
        market_product_resources=resources,
    )
    executor = OnlyEngineBacktestRuntimeExecutor(builder)

    first = executor.execute(_run(case, document, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
    second = executor.execute(_run(case, document, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))

    assert first.result_fingerprint == second.result_fingerprint
    assert first.determinism_fingerprint == second.determinism_fingerprint
    assert first.artifacts[0][0] == "result.json"
