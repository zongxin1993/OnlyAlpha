from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig, OnlyEngineRunResult
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.conformance.cn_a_share_production.support import (
    OnlyCnAshareProductRun,
    only_cn_a_share_product_config,
    only_run_cn_a_share_product,
)
from tests.integration.virtual_multi_fill_support import OnlyPlanCursorCheckpointFailureStoreFactory
from tests.runtime_runner import only_copy_cluster_strategy_revision, only_migrate_cluster_to_strategy

pytestmark = pytest.mark.conformance


def _artifact_content_fingerprint(result: OnlyEngineRunResult) -> str:
    manifest_path = result.manifest_path
    assert manifest_path is not None
    payload = json.loads((manifest_path.parent / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    fingerprint = payload.get("artifact_content_fingerprint")
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    return fingerprint


def _economic_summary(run: OnlyCnAshareProductRun) -> Mapping[str, object]:
    result = run.runtime_result
    return {
        "orders": tuple(
            (item.side, item.status, item.quantity, item.filled_quantity, item.remaining_quantity, item.fill_count)
            for item in result.orders
        ),
        "trades": tuple(
            (
                item.order_side,
                item.fill_quantity,
                item.fill_price,
                item.fee_total_charges,
                item.realized_pnl_delta,
                item.position_quantity_after,
            )
            for item in result.trades
        ),
        "positions": result.final_positions,
        "allocations": result.final_allocations,
        "account_cash": result.final_account.cash,
        "account_pnl": result.final_account.realized_pnl,
        "account_fees": result.final_account.fees,
        "reconciliation": (result.reconciliation.status, result.reconciliation.differences),
    }


def test_memory_and_sqlite_execute_the_same_production_economics(tmp_path: Path) -> None:
    memory = only_run_cn_a_share_product(
        tmp_path / "memory",
        engine_id="p43-persistence-equivalence",
        config=only_cn_a_share_product_config(persistence_backend="MEMORY", multi_fill=True),
    )
    sqlite = only_run_cn_a_share_product(
        tmp_path / "sqlite",
        engine_id="p43-persistence-equivalence",
        config=only_cn_a_share_product_config(persistence_backend="SQLITE", multi_fill=True),
    )

    assert memory.engine_result.status == "COMPLETED", memory.engine_result.failures
    assert sqlite.engine_result.status == "COMPLETED", sqlite.engine_result.failures
    assert _economic_summary(memory) == _economic_summary(sqlite)


@pytest.mark.parametrize("persistence_backend", ("MEMORY", "SQLITE"))
def test_same_product_input_has_deterministic_result_and_artifact(
    tmp_path: Path,
    persistence_backend: str,
) -> None:
    config = only_cn_a_share_product_config(persistence_backend=persistence_backend, multi_fill=True)
    first = only_run_cn_a_share_product(tmp_path / "first", engine_id="p43-determinism", config=config)
    second = only_run_cn_a_share_product(tmp_path / "second", engine_id="p43-determinism", config=config)

    assert first.engine_result.status == "COMPLETED", first.engine_result.failures
    assert second.engine_result.status == "COMPLETED", second.engine_result.failures
    assert first.runtime_result.result_fingerprint == second.runtime_result.result_fingerprint
    assert first.runtime_result.determinism_fingerprint == second.runtime_result.determinism_fingerprint
    assert only_backtest_business_projection(first.runtime_result) == only_backtest_business_projection(
        second.runtime_result
    )
    assert _artifact_content_fingerprint(first.engine_result) == _artifact_content_fingerprint(second.engine_result)


@pytest.mark.recovery
def test_sqlite_a_b_c_forward_recovery_equals_uninterrupted_product_history(tmp_path: Path) -> None:
    recovered_root = tmp_path / "recovered"
    config = only_migrate_cluster_to_strategy(
        only_cn_a_share_product_config(persistence_backend="SQLITE", multi_fill=True), recovered_root
    )
    engine_id = OnlyEngineId("p43-abc-recovery")

    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, recovered_root),
        services=only_default_engine_services(
            runtime_persistence_store_factory=OnlyPlanCursorCheckpointFailureStoreFactory(1)
        ),
    )
    engine_a.add_cluster(config)
    result_a = engine_a.run()
    assert result_a.status == "FAILED"

    engine_b = OnlyEngine(
        OnlyEngineConfig(engine_id, recovered_root),
        services=only_default_engine_services(
            runtime_persistence_store_factory=OnlyPlanCursorCheckpointFailureStoreFactory(2)
        ),
    )
    engine_b.add_cluster(config)
    result_b = engine_b.run()
    assert result_b.status == "FAILED"

    engine_c = OnlyEngine(OnlyEngineConfig(engine_id, recovered_root))
    engine_c.add_cluster(config)
    result_c = engine_c.run()
    assert result_c.status == "COMPLETED", result_c.failures

    baseline_root = tmp_path / "baseline"
    baseline = OnlyEngine(OnlyEngineConfig(engine_id, baseline_root))
    baseline.add_cluster(only_copy_cluster_strategy_revision(config, recovered_root, baseline_root))
    baseline_result = baseline.run()
    assert baseline_result.status == "COMPLETED", baseline_result.failures

    recovered = result_c.runtime_results[0]
    uninterrupted = baseline_result.runtime_results[0]
    assert recovered.result_fingerprint == uninterrupted.result_fingerprint
    assert recovered.determinism_fingerprint == uninterrupted.determinism_fingerprint
    assert only_backtest_business_projection(recovered) == only_backtest_business_projection(uninterrupted)
    assert recovered.facts.runtime_transactions == uninterrupted.facts.runtime_transactions
    assert recovered.facts.executions == uninterrupted.facts.executions
    assert recovered.facts.fees == uninterrupted.facts.fees
    assert recovered.facts.settlement_maturities == uninterrupted.facts.settlement_maturities
    assert _artifact_content_fingerprint(result_c) == _artifact_content_fingerprint(baseline_result)

    diagnostics = engine_c.runtime_sessions[0].runtime.runtime_recovery_diagnostics
    assert diagnostics
    assert diagnostics[-1].checkpoint_sequence >= 2
    assert diagnostics[-1].final_ready_sequence >= diagnostics[-1].covered_execution_sequence
    assert all(item.projection_ready for item in recovered.facts.runtime_transactions)

    # Both failed Engine instances reached the same durable Runtime identity, not test-only shadow stores.
    assert engine_a.runtime_sessions[0].runtime_id == engine_b.runtime_sessions[0].runtime_id
    assert engine_b.runtime_sessions[0].runtime_id == engine_c.runtime_sessions[0].runtime_id
