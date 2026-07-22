"""Formal Scenario vertical slice: Parser/Planner -> OnlyEngine -> assertions/artifact."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.runtime.backtest.result import OnlyBacktestResult
from onlyalpha.scenario.assertions import OnlyScenarioAssertionEngine, OnlyScenarioAssertionSummary
from onlyalpha.scenario.errors import OnlyScenarioError
from onlyalpha.scenario.fingerprint import only_scenario_fingerprint
from onlyalpha.scenario.models import OnlyMarketScenario, OnlyScenarioFactType
from onlyalpha.scenario.parser import OnlyMarketScenarioParser
from onlyalpha.scenario.planning import OnlyMarketScenarioPlan, OnlyMarketScenarioPlanner


@dataclass(frozen=True, slots=True)
class OnlyMarketScenarioRunRequest:
    source: str | Path | OnlyMarketScenario
    output_root: Path


@dataclass(frozen=True, slots=True)
class OnlyMarketScenarioRunResult:
    scenario_id: str
    scenario_version: str
    status: str
    plan: OnlyMarketScenarioPlan
    assertions: OnlyScenarioAssertionSummary
    facts: Mapping[OnlyScenarioFactType, tuple[Mapping[str, object], ...]]
    input_fingerprint: str
    result_fingerprint: str
    artifact_path: Path | None
    diagnostics: tuple[str, ...] = ()


class OnlyMarketScenarioRunner:
    """Application service. It owns no Broker, Risk, Execution or state Manager."""

    def __init__(self) -> None:
        self._parser = OnlyMarketScenarioParser()
        self._planner = OnlyMarketScenarioPlanner()
        self._assertions = OnlyScenarioAssertionEngine()

    def run(self, request: OnlyMarketScenarioRunRequest) -> OnlyMarketScenarioRunResult:
        scenario = (
            request.source if isinstance(request.source, OnlyMarketScenario) else self._parser.load(request.source)
        )
        plan = self._planner.plan(scenario)
        if not plan.executable:
            issue = plan.issues[0]
            raise OnlyScenarioError(issue.code, issue.message, path=issue.path)
        output = request.output_root.resolve()
        from onlyalpha.domain.identifiers import OnlyEngineId
        from onlyalpha.engine import OnlyEngine, OnlyEngineConfig

        engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId(f"scenario-{scenario.scenario_id}"), output))
        engine.add_cluster(scenario.engine_config)
        engine_result = engine.run()
        projections = tuple(engine_result.cluster_results)
        backtest = next((item for item in engine_result.runtime_results if isinstance(item, OnlyBacktestResult)), None)
        facts = self._facts(projections, backtest)
        assertion_summary = self._assertions.evaluate(scenario.expectations, facts)
        status = "ERROR" if engine_result.status != "COMPLETED" else "PASSED" if assertion_summary.passed else "FAILED"
        diagnostics = tuple(engine_result.failures)
        result_fingerprint = only_scenario_fingerprint(
            {
                "scenario": str(scenario.scenario_id),
                "version": str(scenario.version),
                "engine_fingerprint": engine_result.determinism_fingerprint,
                "facts": facts,
                "assertions": assertion_summary,
                "diagnostics": diagnostics,
            }
        )
        artifact_path = self._write_artifact(
            output / "scenario_artifacts" / f"{scenario.scenario_id}-{scenario.version}",
            scenario,
            plan,
            facts,
            assertion_summary,
            status,
            result_fingerprint,
            diagnostics,
        )
        return OnlyMarketScenarioRunResult(
            str(scenario.scenario_id),
            str(scenario.version),
            status,
            plan,
            assertion_summary,
            facts,
            plan.input_fingerprint,
            result_fingerprint,
            artifact_path,
            diagnostics,
        )

    @staticmethod
    def _facts(
        projections: Sequence[Mapping[str, object]],
        backtest: OnlyBacktestResult | None,
    ) -> Mapping[OnlyScenarioFactType, tuple[Mapping[str, object], ...]]:
        result: dict[OnlyScenarioFactType, list[Mapping[str, object]]] = {item: [] for item in OnlyScenarioFactType}
        for projection in projections:
            for item in cast(Sequence[object], projection.get("orders", [])):
                if isinstance(item, Mapping):
                    record = dict(item)
                    metadata = record.get("metadata")
                    if isinstance(metadata, Mapping) and metadata.get("scenario_action_id") is not None:
                        record["action_id"] = metadata["scenario_action_id"]
                    result[OnlyScenarioFactType.ORDER].append(record)
            for item in cast(Sequence[object], projection.get("trades", [])):
                if isinstance(item, Mapping):
                    result[OnlyScenarioFactType.EXECUTION].append(dict(item))
            for key, fact_type in (("final_positions", OnlyScenarioFactType.POSITION),):
                for item in cast(Sequence[object], projection.get(key, [])):
                    if isinstance(item, Mapping):
                        result[fact_type].append(dict(item))
            final_account = projection.get("final_account")
            if isinstance(final_account, Mapping):
                result[OnlyScenarioFactType.ACCOUNT].append(dict(final_account))
            for cluster in cast(Sequence[object], projection.get("cluster_results", [])):
                if not isinstance(cluster, Mapping):
                    continue
                extension = cluster.get("strategy_result_extension")
                if isinstance(extension, Mapping):
                    for item in cast(Sequence[object], extension.get("scenario_actions", [])):
                        if isinstance(item, Mapping):
                            result[OnlyScenarioFactType.ACTION].append(dict(item))
        if backtest is not None:
            standard = {
                OnlyScenarioFactType.ORDER: backtest.facts.orders,
                OnlyScenarioFactType.EXECUTION: backtest.facts.executions,
                OnlyScenarioFactType.POSITION: backtest.facts.positions,
                OnlyScenarioFactType.ACCOUNT: backtest.facts.accounts,
                OnlyScenarioFactType.MARKET_RULE_DECISION: backtest.facts.market_rule_decisions,
                OnlyScenarioFactType.SETTLEMENT: backtest.facts.settlements,
                OnlyScenarioFactType.MARGIN: backtest.facts.margin,
                OnlyScenarioFactType.FEE: backtest.facts.fees,
                OnlyScenarioFactType.PROFILE_TIMELINE: backtest.facts.profile_timeline,
                OnlyScenarioFactType.COMPILED_RULE: backtest.facts.compiled_market_rules,
            }
            for fact_type, records in standard.items():
                result[fact_type] = [
                    {item.name: getattr(record, item.name) for item in fields(record)} for record in records
                ]
            for record_value in result[OnlyScenarioFactType.ORDER]:
                record = cast(dict[str, object], record_value)
                request_id = str(record.get("request_id", ""))
                if request_id.startswith("scenario-"):
                    record["action_id"] = request_id.removeprefix("scenario-")
        return {key: tuple(value) for key, value in result.items()}

    @staticmethod
    def _write_artifact(
        root: Path,
        scenario: OnlyMarketScenario,
        plan: OnlyMarketScenarioPlan,
        facts: Mapping[OnlyScenarioFactType, tuple[Mapping[str, object], ...]],
        assertions: OnlyScenarioAssertionSummary,
        status: str,
        result_fingerprint: str,
        diagnostics: tuple[str, ...],
    ) -> Path:
        root.mkdir(parents=True, exist_ok=False)
        payloads = {
            "scenario_definition.json": {"scenario_id": str(scenario.scenario_id), "version": str(scenario.version)},
            "scenario_plan.json": {"input_fingerprint": plan.input_fingerprint, "commands": len(plan.commands)},
            "scenario_summary.json": {"status": status, "result_fingerprint": result_fingerprint},
            "diagnostics.json": {"diagnostics": list(diagnostics)},
        }
        for name, payload in payloads.items():
            (root / name).write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        datasets = {
            "scenario_actions.parquet": facts[OnlyScenarioFactType.ACTION],
            "scenario_assertions.parquet": tuple(
                {"assertion_id": item.assertion_id, "status": item.status.value, "message": item.message}
                for item in assertions.results
            ),
            "orders.parquet": facts[OnlyScenarioFactType.ORDER],
            "executions.parquet": facts[OnlyScenarioFactType.EXECUTION],
            "positions.parquet": facts[OnlyScenarioFactType.POSITION],
            "accounts.parquet": facts[OnlyScenarioFactType.ACCOUNT],
            "settlements.parquet": facts[OnlyScenarioFactType.SETTLEMENT],
            "margin.parquet": facts[OnlyScenarioFactType.MARGIN],
            "fees.parquet": facts[OnlyScenarioFactType.FEE],
            "market_rule_decisions.parquet": facts[OnlyScenarioFactType.MARKET_RULE_DECISION],
            "profile_timeline.parquet": facts[OnlyScenarioFactType.PROFILE_TIMELINE],
            "compiled_market_rules.parquet": facts[OnlyScenarioFactType.COMPILED_RULE],
        }
        manifest: dict[str, object] = {"schema_version": "1", "result_fingerprint": result_fingerprint, "datasets": {}}
        for name, rows in datasets.items():
            normalized = [
                {key: json.dumps(value, default=str, sort_keys=True) for key, value in row.items()} for row in rows
            ]
            table = (
                pa.Table.from_pylist(normalized)
                if normalized
                else pa.table({"schema_version": pa.array([], pa.string())})
            )
            pq.write_table(table, root / name)
            digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
            manifest["datasets"][name] = {  # type: ignore[index]
                "row_count": table.num_rows,
                "schema": str(table.schema),
                "sha256": digest,
            }
        (root / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        return root
