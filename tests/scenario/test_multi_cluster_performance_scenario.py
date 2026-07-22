import json
from decimal import Decimal
from pathlib import Path
from typing import cast

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig


def _config(path: str, capital: str) -> OnlyClusterRunConfig:
    payload = cast(dict[str, object], json.loads(Path(path).read_text(encoding="utf-8")))
    cluster = cast(dict[str, object], payload["cluster"])
    cluster["capital"] = {"mode": "FIXED_CAPITAL", "amount": capital, "currency": "CNY"}
    return OnlyClusterRunConfig.from_mapping(payload, source_path=path)


def test_engine_multi_cluster_performance_full_vertical_slice(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("multi-cluster-performance-scenario"), tmp_path))
    engine.add_cluster(_config("tests/fixtures/legacy_macd/cluster.json", "400000.00"))
    engine.add_cluster(_config("tests/fixtures/legacy_macd/cluster_fast.json", "600000.00"))

    run = engine.run()
    result = run.runtime_results[0]
    clusters = {str(item.cluster_id): item.performance for item in result.cluster_results}  # type: ignore[attr-defined]

    assert run.status == "COMPLETED"
    assert len(run.runtime_results) == 1
    assert set(clusters) == {"macd-demo", "macd-fast-demo"}
    assert clusters["macd-demo"].initial_equity.amount == Decimal("400000.00")
    assert clusters["macd-fast-demo"].initial_equity.amount == Decimal("600000.00")
    assert clusters["macd-demo"].net_pnl.amount > 0
    assert clusters["macd-fast-demo"].net_pnl.amount < 0
    assert clusters["macd-demo"].fees.amount != clusters["macd-fast-demo"].fees.amount
    assert {str(item.instrument_id) for item in result.trades} == {"TESTETF.XSHG"}  # type: ignore[attr-defined]
    assert result.runtime_performance.net_pnl.amount == sum(  # type: ignore[attr-defined]
        (item.net_pnl.amount for item in clusters.values()), Decimal(0)
    )
    assert result.runtime_performance.fees.amount == sum(  # type: ignore[attr-defined]
        (item.fees.amount for item in clusters.values()), Decimal(0)
    )
    assert result.runtime_performance.final_equity.amount == sum(  # type: ignore[attr-defined]
        (item.final_equity.amount for item in clusters.values()), Decimal(0)
    )
    assert result.reconciliation.status == "MATCHED"  # type: ignore[attr-defined]
    assert run.manifest_path is not None
    artifact_root = run.manifest_path.parent
    assert (artifact_root / "summary.json").is_file()
    assert (artifact_root / "equity.parquet").is_file()
    assert (artifact_root / "cluster_equity.parquet").is_file()
    assert (artifact_root / "report.md").is_file()
