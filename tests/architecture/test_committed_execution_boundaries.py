import ast
from dataclasses import fields
from pathlib import Path
from typing import get_type_hints

from onlyalpha.execution import OnlyCommittedExecutionFact, OnlyCommittedExecutionJournal, OnlyExecutionProcessor
from onlyalpha.runtime.runtime import OnlyRuntimeServices


def _source(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(root.rglob("*.py")))


def test_committed_fact_and_runtime_service_have_provider_neutral_runtime_ownership() -> None:
    fact_modules = {getattr(field.type, "__module__", "") for field in fields(OnlyCommittedExecutionFact)}
    assert not any(module.startswith("onlyalpha_plugin_") for module in fact_modules)
    service_hints = get_type_hints(OnlyRuntimeServices)
    assert service_hints["committed_execution_journal"] is OnlyCommittedExecutionJournal


def test_result_collector_has_no_broker_query_or_virtual_broker_dependency() -> None:
    collector = Path("src/onlyalpha/collector/backtest.py")
    tree = ast.parse(collector.read_text(encoding="utf-8"))
    calls = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert "query_trades" not in calls
    assert not any(name.startswith("onlyalpha_plugin_broker_virtual") for name in imports)


def test_processor_is_the_only_production_committed_journal_writer() -> None:
    execution_root = Path("src/onlyalpha/execution")
    writers: list[Path] = []
    for path in execution_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "_committed_executions"
            for node in ast.walk(tree)
        ):
            writers.append(path)
    assert writers == [Path("src/onlyalpha/execution/processor.py")]
    assert OnlyExecutionProcessor.__module__ == "onlyalpha.execution.processor"


def test_plugins_cannot_construct_or_write_runtime_committed_facts() -> None:
    plugins = _source(Path("packages/provider"))
    assert "OnlyCommittedExecutionFact" not in plugins
    assert "OnlyCommittedExecutionJournal" not in plugins


def test_analytics_and_artifact_do_not_resolve_fees_or_market_rules() -> None:
    downstream = _source(Path("src/onlyalpha/analytics")) + _source(Path("src/onlyalpha/artifact"))
    assert "OnlyFeeResolver" not in downstream
    assert "OnlyMarketRuleEngine" not in downstream
