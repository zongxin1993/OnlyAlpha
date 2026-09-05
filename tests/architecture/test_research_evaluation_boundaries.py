import ast
from dataclasses import replace
from pathlib import Path

import pytest
from onlyalpha_example_alpha.registration import MOMENTUM
from onlyalpha_plugin_indicators.registration import TYPES, resolve_definition
from onlyalpha_plugin_targets.registration import resolve_forward_return

from onlyalpha.calculation import (
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationReference,
)
from onlyalpha.runtime.research.factory import OnlyResearchRuntimeFactory

pytestmark = pytest.mark.architecture


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def _target(exit_offset: int = 2):
    return resolve_forward_return(
        {"entry_offset": 0, "exit_offset": exit_offset},
        OnlyCalculationReference(None, "entry_price", "bar.close"),
        OnlyCalculationReference(None, "exit_price", "bar.close"),
    )


def test_target_dataset_source_is_allowed_and_target_graph_is_independent() -> None:
    target5 = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(_target(5)),))
    target20 = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(_target(20)),))
    assert target5.fingerprint != target20.fingerprint
    indicator = resolve_definition(TYPES[0], {"period": 2})
    feature = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(indicator),))
    assert (
        feature.fingerprint == OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(indicator),)).fingerprint
    )


@pytest.mark.parametrize("consumer_kind", ("indicator", "factor"))
def test_feature_consuming_target_output_fails_at_graph_construction(consumer_kind: str) -> None:
    target = _target()
    if consumer_kind == "indicator":
        base = resolve_definition(TYPES[0], {"period": 2})
        consumer = replace(
            base,
            input_bindings={"value": OnlyCalculationReference(target.fingerprint, "target_value")},
        )
    else:
        consumer = MOMENTUM.resolve(
            {},
            {
                "return_short": OnlyCalculationReference(target.fingerprint, "target_value"),
                "return_long": OnlyCalculationReference(target.fingerprint, "target_value"),
            },
            target.warmup,
        )
    with pytest.raises(ValueError, match="separate graphs"):
        OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(target), OnlyCalculationNodeDefinition(consumer)))


@pytest.mark.parametrize("dependency", ("indicator", "factor", "target"))
def test_target_consuming_any_calculation_node_fails_in_v1(dependency: str) -> None:
    target = _target()
    if dependency == "indicator":
        upstream = resolve_definition(TYPES[0], {"period": 2})
    elif dependency == "factor":
        upstream = MOMENTUM.resolve(
            {},
            {
                "return_short": OnlyCalculationReference(None, "value", "bar.close"),
                "return_long": OnlyCalculationReference(None, "value", "bar.close"),
            },
            target.warmup,
        )
    else:
        upstream = _target(3)
    dependent = replace(
        target,
        input_bindings={
            "entry_price": OnlyCalculationReference(upstream.fingerprint, upstream.outputs[0].name),
            "exit_price": OnlyCalculationReference(None, "exit_price", "bar.close"),
        },
    )
    message = "separate graphs" if dependency != "target" else "Target V1"
    with pytest.raises(ValueError, match=message):
        OnlyCalculationGraphDefinition(
            (OnlyCalculationNodeDefinition(upstream), OnlyCalculationNodeDefinition(dependent))
        )


def test_evaluation_plane_has_no_trading_authority_imports() -> None:
    forbidden = (
        "onlyalpha.runtime",
        "onlyalpha.cluster",
        "onlyalpha.strategy",
        "onlyalpha.broker",
        "onlyalpha.account",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.risk",
        "onlyalpha.reservation",
        "onlyalpha.execution",
        "onlyalpha.transaction",
    )
    roots = (
        Path("src/onlyalpha/research/evaluation"),
        Path("plugs/onlyalpha-plugin-targets/src/onlyalpha_plugin_targets"),
    )
    for root in roots:
        for path in root.rglob("*.py"):
            imports = _imports(path)
            assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_summary_statistics_has_no_downstream_research_or_product_dependencies() -> None:
    forbidden = (
        "onlyalpha.research.result",
        "onlyalpha.research.artifact",
        "onlyalpha.research.query",
        "onlyalpha.research.specification",
        "onlyalpha.strategy",
        "onlyalpha.runtime",
        "onlyalpha.broker",
        "onlyalpha.account",
        "onlyalpha.risk",
        "onlyalpha.portfolio",
        "onlyalpha.execution",
        "onlyalpha.web",
    )
    for path in Path("src/onlyalpha/research/evaluation/summary").rglob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_research_runtime_factory_is_formally_activated_after_p7_11() -> None:
    assert OnlyResearchRuntimeFactory().runtime_type == "RESEARCH"
