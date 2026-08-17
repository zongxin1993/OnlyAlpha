from __future__ import annotations

from onlyalpha_plugin_targets.registration import FORWARD_RETURN
from onlyalpha_plugin_targets.registration import registrations as target_registrations

from onlyalpha.calculation import OnlyCalculationKind
from onlyalpha.research import (
    OnlyResearchCalculationSpec,
    OnlyResearchGraphTemplate,
    OnlyResearchGraphTemplateNode,
    OnlyResearchSeriesSelector,
    OnlyResearchSpecification,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticsSpec,
    OnlyResearchTemplateInputBinding,
    OnlyResearchTemplateReference,
)
from tests.research.evaluation.support import evaluation_registry
from tests.research.sweep.support import factor_template, reference


def target_template() -> OnlyResearchGraphTemplate:
    return OnlyResearchGraphTemplate(
        (
            OnlyResearchGraphTemplateNode(
                "forward_return",
                reference(OnlyCalculationKind.TARGET, FORWARD_RETURN.type_id),
                {"exit_offset": 1},
                (
                    OnlyResearchTemplateInputBinding(
                        "entry_price", OnlyResearchTemplateReference(None, "entry_price", "bar.close")
                    ),
                    OnlyResearchTemplateInputBinding(
                        "exit_price", OnlyResearchTemplateReference(None, "exit_price", "bar.close")
                    ),
                ),
            ),
        )
    )


def specification(dataset: str = "a" * 64) -> OnlyResearchSpecification:
    return OnlyResearchSpecification(
        dataset,
        (
            OnlyResearchCalculationSpec("feature", factor_template()),
            OnlyResearchCalculationSpec("target", target_template()),
        ),
        (
            OnlyResearchStatisticsSpec(
                OnlyResearchSeriesSelector("feature", "momentum", "factor_value"),
                OnlyResearchSeriesSelector("target", "forward_return", "target_value"),
                OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC),
            ),
        ),
    )


def registry():
    # evaluation_registry already includes the exact Target registration; retain this
    # assertion so test fixtures cannot silently lose that capability.
    result = evaluation_registry()
    assert target_registrations()
    return result
