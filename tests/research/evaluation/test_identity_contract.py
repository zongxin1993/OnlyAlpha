from __future__ import annotations

import subprocess
import sys

import pytest
from onlyalpha_plugin_factors.registration import resolve_momentum
from onlyalpha_plugin_indicators.registration import TYPES, resolve_definition

from onlyalpha.calculation import OnlyCalculationReference
from onlyalpha.research.evaluation import (
    OnlyResearchFeatureSeriesReference,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticsPlan,
    OnlyResearchTargetSeriesReference,
)
from tests.research.factor.support import factor_graph


def _plan(
    method: OnlyResearchStatisticsMethod = OnlyResearchStatisticsMethod.IC,
    minimum: int = 2,
) -> OnlyResearchStatisticsPlan:
    return OnlyResearchStatisticsPlan(
        OnlyResearchFeatureSeriesReference("a" * 64, "b" * 64, "factor_value"),
        OnlyResearchTargetSeriesReference("c" * 64, "d" * 64, "target_value"),
        OnlyResearchStatisticsDefinition(method, minimum),
    )


def test_statistics_identity_is_canonical_semantic_and_round_trips() -> None:
    baseline = _plan()
    assert OnlyResearchStatisticsPlan.from_dict(baseline.to_dict()) == baseline
    assert baseline.statistics_fingerprint == _plan().statistics_fingerprint
    assert baseline.statistics_fingerprint != _plan(OnlyResearchStatisticsMethod.RANK_IC).statistics_fingerprint
    assert baseline.statistics_fingerprint != _plan(minimum=3).statistics_fingerprint


def test_target_kind_extension_preserves_existing_indicator_factor_and_graph_fingerprints() -> None:
    indicator = resolve_definition(TYPES[0], {"period": 2})
    factor = resolve_momentum(
        {},
        OnlyCalculationReference(None, "x", "bar.close"),
        OnlyCalculationReference(None, "x", "bar.close"),
    )
    assert indicator.fingerprint == "49d97b301c4879ce787c87c1745a965fb8dc4ed1c037d4a9fd082e4bafb069c3"
    assert factor.fingerprint == "148722d0c89cdcd47bf4cef94a0d4179abf579c3d01e49fd70f6ef55c435f02d"
    assert factor_graph().fingerprint == "94220fca8f569c34bba94073dda8808d0060ddb9ce904100c7732cfbfd7f0cf3"


def test_statistics_identity_is_stable_in_fresh_process() -> None:
    script = """
from onlyalpha.research.evaluation import *
p = OnlyResearchStatisticsPlan(
    OnlyResearchFeatureSeriesReference('a' * 64, 'b' * 64, 'factor_value'),
    OnlyResearchTargetSeriesReference('c' * 64, 'd' * 64, 'target_value'),
    OnlyResearchStatisticsDefinition(OnlyResearchStatisticsMethod.IC),
)
print(p.statistics_fingerprint)
"""
    result = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == _plan().statistics_fingerprint


@pytest.mark.parametrize(
    "change",
    (
        {"minimum_observations": 1},
        {"method": "UNKNOWN"},
        {"pairing_policy": "OUTER"},
    ),
)
def test_statistics_definition_fails_closed(change: dict[str, object]) -> None:
    payload = _plan().definition.to_dict()
    payload.update(change)
    with pytest.raises((TypeError, ValueError)):
        OnlyResearchStatisticsDefinition.from_dict(payload)
