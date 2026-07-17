from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.factor.config import OnlyFactorConfig, OnlyFactorType, OnlyIndicatorSpec
from onlyalpha.factor.identifiers import OnlyFactorId


@dataclass(frozen=True, slots=True)
class OnlyMacdSignalFactorConfig(OnlyFactorConfig):
    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> OnlyMacdSignalFactorConfig:
        raw_specs = values.get("indicator_specs", ())
        if not isinstance(raw_specs, tuple) or len(raw_specs) != 1 or not isinstance(raw_specs[0], Mapping):
            raise ValueError("MACD Signal Factor requires exactly one MACD indicator spec")
        raw = raw_specs[0]
        return cls(
            factor_id=values["factor_id"]
            if isinstance(values["factor_id"], OnlyFactorId)
            else OnlyFactorId(str(values["factor_id"])),
            factor_type=OnlyFactorType(str(values["factor_type"])),
            indicators=(
                OnlyIndicatorSpec(
                    raw["indicator_id"],
                    raw["indicator_type"],
                    raw["bar_type"],
                    raw["parameters"],
                ),
            ),
            dependencies=tuple(values.get("dependencies", ())),
            required=bool(values.get("required", True)),
            extensions={
                key: value
                for key, value in values.items()
                if key not in {"factor_id", "factor_type", "indicator_specs", "dependencies", "required"}
            },
        )
