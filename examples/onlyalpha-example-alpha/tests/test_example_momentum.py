import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
from onlyalpha_example_alpha.provider import quant_asset_provider
from onlyalpha_example_alpha.registration import MOMENTUM, registrations, resolve_momentum
from onlyalpha_example_alpha.research import OnlyExampleResearchMomentumBackend
from onlyalpha_example_alpha.trading import OnlyExampleTradingMomentumBackendFactory

from onlyalpha.calculation import (
    FACTOR_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationStateCapability,
    OnlyFactorKind,
)
from onlyalpha.quant_assets import only_quant_asset_distribution_artifact_manifest
from onlyalpha.runtime.generation import OnlyCoreExecutionIdentity

_D = pa.decimal128(38, 12)


def _definition():
    return resolve_momentum(
        {"short_weight": "0.25", "long_weight": "0.75"},
        OnlyCalculationReference("a" * 64, "value"),
        OnlyCalculationReference("b" * 64, "value"),
    )


def test_example_momentum_is_one_hypothesis_bearing_l3_factor() -> None:
    assert MOMENTUM.kind is OnlyCalculationKind.FACTOR
    assert MOMENTUM.factor_kind is OnlyFactorKind.TIME_SERIES
    assert MOMENTUM.type_id == "example.factor.momentum"
    assert MOMENTUM.outputs[0].semantic_type == FACTOR_VALUE_SEMANTIC_TYPE
    assert {item.name for item in MOMENTUM.inputs} == {"return_short", "return_long"}
    assert not any(token in MOMENTUM.type_id for token in ("rolling_return", "rank", "zscore", "moving_average"))


def test_research_and_trading_backends_are_exactly_equivalent_for_values_and_nulls() -> None:
    definition = _definition()
    research = (
        OnlyExampleResearchMomentumBackend()
        .execute(
            definition,
            {
                "return_short": pa.array([Decimal("1"), None, Decimal("-1")], type=_D),
                "return_long": pa.array([Decimal("3"), Decimal("2"), Decimal("1")], type=_D),
            },
        )["factor_value"]
        .to_pylist()
    )
    trading = OnlyExampleTradingMomentumBackendFactory().create(definition, object())
    incremental = [
        trading.update({"return_short": short, "return_long": long})["factor_value"]
        for short, long in ((Decimal("1"), Decimal("3")), (None, Decimal("2")), (Decimal("-1"), Decimal("1")))
    ]
    assert research == incremental == [Decimal("2.500000000000"), None, Decimal("0.500000000000")]


def test_example_factor_registrations_bind_manifests_and_state_capability() -> None:
    actual = registrations()
    assert len(actual) == 2
    assert {item.backend for item in actual} == {
        OnlyCalculationBackendKind.RESEARCH,
        OnlyCalculationBackendKind.TRADING,
    }
    assert all(item.implementation_manifest is not None for item in actual)
    trading = next(item for item in actual if item.backend is OnlyCalculationBackendKind.TRADING)
    assert trading.state_capability is OnlyCalculationStateCapability.STATELESS


def test_example_factor_can_bind_the_public_immutable_distribution_contract() -> None:
    core = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", "a" * 64)
    manifest = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-example-alpha",
        source_revision="b" * 40,
        artifact_logical_name="onlyalpha_example_alpha-0.9.9-py3-none-any.whl",
        artifact_bytes=b"example alpha wheel",
        tested_core_execution_fingerprint=core.fingerprint,
        provider=quant_asset_provider(),
    )
    assert manifest.provider_id == "example.alpha.library"
    assert {item.backend for item in manifest.implementations} == {"RESEARCH", "TRADING"}


def test_l3_checkout_supports_explicit_source_path_import(tmp_path: Path) -> None:
    source = Path("examples/onlyalpha-example-alpha/src").resolve()
    script = f"""
import pathlib
import sys
sys.path.insert(0, {str(source)!r})
import onlyalpha_example_alpha
from onlyalpha_example_alpha.provider import quant_asset_provider
assert pathlib.Path(onlyalpha_example_alpha.__file__).resolve().is_relative_to(pathlib.Path({str(source)!r}))
assert {{item.type_definition.type_id for item in onlyalpha_example_alpha.registrations()}} == {{'example.factor.momentum'}}
assert quant_asset_provider().manifest.provider_id == 'example.alpha.library'
"""
    subprocess.run([sys.executable, "-I", "-c", script], cwd=tmp_path, check=True)
