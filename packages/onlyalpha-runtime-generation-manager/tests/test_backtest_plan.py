from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from onlyalpha.backtest import (
    OnlyBacktestDeploymentCatalog,
    OnlyBacktestMarketProductResourceRegistry,
    only_default_backtest_profile_registry,
)
from onlyalpha.backtest.model import OnlyBacktestLimitPolicy
from onlyalpha.backtest.worker import OnlyBacktestProductEnginePlanBuilder
from onlyalpha.strategy import OnlyFrozenStrategyRevisionStore
from tests.backtest.test_product_engine import _deployment, _run
from tests.research.calculation.support import bars
from tests.strategy.product_support import publish_frozen_strategy_for_execution_test, strategy_product_case


def test_plan_retains_product_revision_and_explicit_policy_and_uses_only_verified_inputs(tmp_path: Path) -> None:
    from onlyalpha_runtime_generation_manager.backtest_plan import (
        only_build_native_backtest_plan,
        only_native_backtest_plan_fingerprint,
    )

    values = tuple(item for item in bars() if str(item.instrument_id) == "A.XNAS")
    case = strategy_product_case(tmp_path / "case", values=values)
    semantic_root = tmp_path / "engine" / "research"
    publish_frozen_strategy_for_execution_test(semantic_root, case.revision)
    document = _deployment(case)
    builder = OnlyBacktestProductEnginePlanBuilder(
        user_data_root=tmp_path / "engine",
        catalog=OnlyBacktestDeploymentCatalog((document,)),
        strategies=OnlyFrozenStrategyRevisionStore(semantic_root),
        datasets=case.dataset_store,
        profiles=only_default_backtest_profile_registry(),
        market_product_resources=OnlyBacktestMarketProductResourceRegistry(),
    )
    historical = _run(case, document, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    specification = replace(
        historical.specification, schema_version=2, order_policy=OnlyBacktestLimitPolicy("4", "10.00", "12.00", "2", 1)
    )
    run = type(historical).queued(
        run_id=historical.run_id,
        specification=specification,
        admission_resolution=historical.admission_resolution,
        queued_at=historical.queued_at,
    )
    _, configs, _ = builder.build(run)
    inputs = {
        "schema_version": 1,
        "sources": [
            {
                "schema_version": 1,
                "source": "c" * 64,
                "snapshot": case.dataset_fingerprint,
                "dataset_binding": run.specification.dataset_binding_fingerprint,
                "data_version": "exact-snapshot",
                "priority": 0,
                "rows": len(values),
            }
        ],
        "records": [
            {
                "schema_version": 1,
                "source": "c" * 64,
                "sequence": i,
                "data_version": "exact-snapshot",
                "bar": bar.to_dict(),
            }
            for i, bar in enumerate(values, 1)
        ],
    }
    plan = only_build_native_backtest_plan(
        run,
        config=configs[0],
        strategy=case.revision,
        inputs=inputs,
        generation="a" * 64,
        native_artifact="e" * 64,
        worker_artifact="f" * 64,
        python=Path(sys.executable),
    )
    identity = only_native_backtest_plan_fingerprint(plan)
    assert identity == only_native_backtest_plan_fingerprint({**plan, "python": "/moved/reader/bin/python"})
    assert identity != only_native_backtest_plan_fingerprint({**plan, "generation": "b" * 64})
    assert identity != only_native_backtest_plan_fingerprint(
        {**plan, "trading": {**plan["trading"], "maximum_fill_quantity": "1"}}
    )
    assert plan["strategy"] == case.revision.to_dict()
    assert plan["node_identities"] == [node.fingerprint for node in case.revision.decision_graph.ordered_nodes]
    assert plan["configuration"]["profiles"][plan["cluster"]]["revision"] == str(case.revision.strategy_fingerprint)
    assert plan["work_id"] == run.run_id.value
    assert plan["inputs"] == inputs
    assert [r["quantity"]["value"] for r in plan["trading"]["requests"]] == ["4", "4"]
    assert [r["side"] for r in plan["trading"]["requests"]] == ["BUY", "SELL"]

    second = type(run).queued(
        run_id=type(run.run_id)("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        specification=run.specification,
        admission_resolution=run.admission_resolution,
        queued_at=run.queued_at,
    )
    other = only_build_native_backtest_plan(
        second,
        config=configs[0],
        strategy=case.revision,
        inputs=inputs,
        generation="a" * 64,
        native_artifact="e" * 64,
        worker_artifact="f" * 64,
        python=Path(sys.executable),
    )
    for field in ("engine", "runtime"):
        assert plan["configuration"][field] != other["configuration"][field], (
            "different formal Runs cannot own the same Runtime identity"
        )


def test_native_admission_refuses_multi_instrument_shape_before_queueing(tmp_path: Path) -> None:
    import pytest
    from onlyalpha_runtime_generation_manager.backtest_runtime import only_validate_native_backtest_specification

    from onlyalpha.backtest.errors import OnlyBacktestError

    case = strategy_product_case(tmp_path / "unsupported")
    document = _deployment(case)
    old = _run(case, document, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    spec = replace(
        old.specification,
        base_currency="CNY",
        schema_version=2,
        order_policy=OnlyBacktestLimitPolicy("1", "10", "11", "1", 1),
    )
    with pytest.raises(OnlyBacktestError, match="BACKTEST_NATIVE_SHAPE_UNSUPPORTED"):
        only_validate_native_backtest_specification(spec, case.revision)
