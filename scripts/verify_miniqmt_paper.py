"""Manual local acceptance for the broker-free MiniQMT Paper market-data chain."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from typing import cast

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.data.enums import OnlyMarketDataProcessingStatus
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine
from onlyalpha.engine.models import OnlyEngineConfig
from onlyalpha.market_data.pipeline import OnlyMarketDataUpdateResult
from onlyalpha.runtime.paper.runtime import OnlyPaperRuntime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("examples/configs/miniqmt_paper_macd.yaml"))
    parser.add_argument("--timeout", type=float, default=420.0)
    parser.add_argument("--required-closed-bars", type=int, default=5)
    args = parser.parse_args()

    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("miniqmt-paper-verification"), Path("user_data")))
    engine.add_cluster(OnlyClusterRunConfig.load(args.config))
    engine.initialize()
    live_started_at = datetime.now(UTC)
    engine.start()
    started = monotonic()
    try:
        runtime = engine.runtimes[0]
        if not isinstance(runtime, OnlyPaperRuntime):
            raise TypeError("Engine did not assemble OnlyPaperRuntime")
        while monotonic() - started < args.timeout:
            applied = tuple(
                item
                for item in runtime.processing_results
                if item.status is OnlyMarketDataProcessingStatus.APPLIED and item.pipeline_result is not None
            )
            live = tuple(
                item
                for item in applied
                if str(item.update_id).startswith("miniqmt-live-")
                and cast(OnlyMarketDataUpdateResult, item.pipeline_result).input_bar.bar_start >= live_started_at
            )
            pipelines = tuple(cast(OnlyMarketDataUpdateResult, item.pipeline_result) for item in live)
            derived_3m = tuple(
                bar for pipeline in pipelines for bar in pipeline.derived_bars if bar.bar_type.specification.step == 3
            )
            orders = runtime.order_snapshots
            failures = tuple(
                item
                for item in runtime.processing_results
                if item.status
                in {
                    OnlyMarketDataProcessingStatus.REJECTED,
                    OnlyMarketDataProcessingStatus.FAILED,
                    OnlyMarketDataProcessingStatus.STALE,
                    OnlyMarketDataProcessingStatus.GAP_DETECTED,
                }
            )
            if len(live) >= args.required_closed_bars and derived_3m and orders and not failures:
                evidence = {
                    "status": "PASSED",
                    "runtime": runtime.runtime_type,
                    "worker_alive": runtime.worker_alive,
                    "closed_1m_live_bars": len(live),
                    "closed_3m_derived_bars": len(derived_3m),
                    "latest_1m_end": pipelines[-1].input_bar.bar_end.isoformat(),
                    "latest_3m_end": derived_3m[-1].bar_end.isoformat(),
                    "orders": len(orders),
                    "fills": sum(item.fill_count for item in orders),
                    "positions": len(runtime.position_manager.snapshot_all()),
                    "fees": len(runtime.fee_manager.records),
                    "settlements": len(runtime.settlement_manager.records),
                    "strategy": dict(runtime.clusters[0].strategy.build_result_extension()),
                }
                print(json.dumps(evidence, ensure_ascii=False, indent=2))
                return 0
            if runtime.worker_failure is not None:
                raise RuntimeError(str(runtime.worker_failure))
            sleep(0.5)
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason": (
                        f"timeout before {args.required_closed_bars} closed live 1m Bars, "
                        "one derived 3m Bar, and one suppressed order intent"
                    ),
                    "processing_results": len(runtime.processing_results),
                    "details": [
                        {
                            "update_id": str(item.update_id),
                            "status": item.status.value,
                            "validation": list(item.validation.reasons),
                            "failure": None
                            if item.failure is None
                            else f"{item.failure.error_type}: {item.failure.message}",
                            "bar_start": None
                            if item.pipeline_result is None
                            else cast(OnlyMarketDataUpdateResult, item.pipeline_result).input_bar.bar_start.isoformat(),
                            "bar_end": None
                            if item.pipeline_result is None
                            else cast(OnlyMarketDataUpdateResult, item.pipeline_result).input_bar.bar_end.isoformat(),
                            "derived_steps": []
                            if item.pipeline_result is None
                            else [
                                bar.bar_type.specification.step
                                for bar in cast(OnlyMarketDataUpdateResult, item.pipeline_result).derived_bars
                            ],
                        }
                        for item in runtime.processing_results
                    ],
                    "strategy": dict(runtime.clusters[0].strategy.build_result_extension()),
                    "orders": [item.to_dict() for item in runtime.order_snapshots],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    finally:
        engine.stop()


if __name__ == "__main__":
    raise SystemExit(main())
