"""Non-publishing native reference for common post-warmup Strategy decisions.

Builds new live definitions separately in each schema. No old record conversion,
Freeze publication, Runtime admission, or claimed identity equivalence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
from typing import Any

from onlyalpha_plugin_indicators.registration import registrations as indicators
from onlyalpha_plugin_operators.registration import registrations as operators

from onlyalpha.calculation.decimal_execution import only_decimal_context
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.domain.market import OnlyBar
from onlyalpha.market_data.resolution import OnlyBarConstructionRecipe, OnlyBarConstructionRequirement
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives
from onlyalpha.strategy.execution import OnlyStrategyExecutionPlan
from onlyalpha.strategy.revision import (
    OnlyStrategyImplementationBinding,
    OnlyStrategyMarketInputContract,
    OnlyStrategyRevision,
    OnlyStrategySignalBinding,
    OnlyStrategySignalSemantics,
    OnlyStrategyUniverse,
)


def reference_decisions(base: dict[str, Any], count: int = 6) -> list[dict[str, object]]:
    registry = OnlyCalculationRegistry()
    for item in (*indicators(), *operators()):
        registry.register(item)
    only_register_trading_predicate_primitives(registry)
    only_register_research_predicate_primitives(registry)
    definitions: list[OnlyCalculationDefinition] = []

    def resolve(
        kind: str, type_id: str, parameters: Mapping[str, object], bindings: Mapping[str, OnlyCalculationReference]
    ) -> OnlyCalculationDefinition:
        d = registry.rematerialize_definition(
            OnlyCalculationTypeReference(OnlyCalculationKind(kind), type_id, "1"), parameters, bindings
        )
        definitions.append(d)
        return d

    external = {"value": OnlyCalculationReference(None, "value", "bar.close")}
    sma = resolve("INDICATOR", "onlyalpha.indicator.sma", {"period": 3}, external)
    resolve("INDICATOR", "onlyalpha.indicator.ema", {"period": 3}, external)
    op = resolve(
        "INDICATOR", "onlyalpha.operator.abs", {}, {"value": OnlyCalculationReference(sma.fingerprint, "value")}
    )
    signals = []
    for role, operator, literal in (
        ("eligibility", "ge", "0"),
        ("entry_signal", "gt", "2"),
        ("exit_signal", "lt", "2"),
    ):
        p = resolve(
            "PREDICATE",
            f"onlyalpha.predicate.internal.compare.{operator}.decimal.literal",
            {"literal": Decimal(literal), "literal_left": False},
            {"left": OnlyCalculationReference(op.fingerprint, "value")},
        )
        terminal = resolve(
            "PREDICATE",
            f"onlyalpha.predicate.internal.terminal.{role}",
            {},
            {"value": OnlyCalculationReference(p.fingerprint, "value")},
        )
        signals.append(OnlyStrategySignalBinding(terminal.fingerprint, "value"))
    b = OnlyBar.from_dict(base)
    bindings = []
    for d in definitions:
        research = registry.resolve(
            d.kind, d.type_id, d.semantic_version, OnlyCalculationBackendKind.RESEARCH
        ).implementation_manifest
        trading = registry.resolve(
            d.kind, d.type_id, d.semantic_version, OnlyCalculationBackendKind.TRADING
        ).implementation_manifest
        assert research is not None and trading is not None
        bindings.append(
            OnlyStrategyImplementationBinding(
                d.fingerprint, research.implementation_fingerprint, trading.implementation_fingerprint
            )
        )
    revision = OnlyStrategyRevision(
        OnlyStrategyUniverse((b.instrument_id,)),
        OnlyStrategyMarketInputContract(
            b.bar_type.semantic,
            OnlyBarConstructionRequirement.exact(OnlyBarConstructionRecipe.provider_native(b.bar_type.semantic)),
        ),
        OnlyCalculationGraphDefinition(tuple(OnlyCalculationNodeDefinition(d) for d in definitions)),
        tuple(sorted(bindings)),
        OnlyStrategySignalSemantics(signals[0], signals[1], signals[2]),
    )
    executor = OnlyStrategyExecutionPlan(revision, registry).new_executor()
    results: list[dict[str, object]] = []
    numeric = replace(sma.numeric, rounding="ROUND_HALF_EVEN")
    for i in range(count):
        row = json.loads(json.dumps(base))
        for field in ("bar_start", "bar_end", "ts_event", "ts_init"):
            row[field] = (getattr(b, field) + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
        for field in ("open", "high", "low", "close"):
            row[field]["value"] = str(i + 1)
        bar = OnlyBar.from_dict(row)
        with localcontext(only_decimal_context(numeric)):
            decision = executor.execute(bar)
        if i >= 2:
            results.append(
                {"minute": i + 1, "eligibility": decision.eligibility, "entry": decision.entry, "exit": decision.exit}
            )
    return results


def compare_reference(stdout: str, base: dict[str, Any]) -> None:
    lines = [
        line.removeprefix("STRATEGY_DECISIONS_JSON ")
        for line in stdout.splitlines()
        if line.startswith("STRATEGY_DECISIONS_JSON ")
    ]
    if len(lines) != 1:
        raise ValueError("STRATEGY_COMPARISON_OUTPUT_MISSING")
    actual = json.loads(lines[0])
    expected = [{"minute": i, "eligibility": True, "entry": i > 3, "exit": False} for i in range(3, 7)]
    assert actual == expected
    assert reference_decisions(base) == expected
    print(
        "STRATEGY native Revision1 and Rust Revision2 common post-warmup decisions match independent expectations; identities intentionally distinct",
        flush=True,
    )
