"""Strict loading of the frozen Paper acceptance profile."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]


@dataclass(frozen=True, slots=True)
class OnlyPaperAcceptancePlan:
    plan_id: str
    runtime_config_path: Path
    output_root: Path
    expected_instrument_id: str
    expected_provider_symbol: str
    external_bar_step_minutes: int = 1
    derived_bar_step_minutes: int = 3
    minimum_historical_bars: int = 50
    target_live_closed_bars: int = 6
    target_live_derived_bars: int = 2
    require_indicator_ready: bool = True
    require_factor_snapshot: bool = True
    require_live_shadow_intent: bool = True
    live_grace_seconds: int = 10
    startup_timeout_seconds: int = 60
    shutdown_timeout_seconds: int = 15

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError("acceptance plan_id cannot be blank")
        if self.expected_instrument_id != "000001.XSHE" or self.expected_provider_symbol != "000001.SZ":
            raise ValueError("Paper acceptance profile is frozen to 000001.XSHE / 000001.SZ")
        if self.external_bar_step_minutes != 1 or self.derived_bar_step_minutes != 3:
            raise ValueError("Paper acceptance profile is frozen to external 1m / internal 3m")
        counts = (
            self.minimum_historical_bars,
            self.target_live_closed_bars,
            self.target_live_derived_bars,
            self.live_grace_seconds,
            self.startup_timeout_seconds,
            self.shutdown_timeout_seconds,
        )
        if any(item <= 0 for item in counts):
            raise ValueError("acceptance counts and timeouts must be positive")

    @classmethod
    def load(cls, path: str | Path, *, output_override: Path | None = None) -> OnlyPaperAcceptancePlan:
        selected = Path(path).resolve()
        raw = yaml.safe_load(selected.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("acceptance plan must be a YAML object")
        allowed = {item.name for item in cls.__dataclass_fields__.values()}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown acceptance plan fields: {sorted(unknown)}")
        values = dict(raw)
        runtime_path = Path(str(values["runtime_config_path"]))
        configured_output = Path(str(values.get("output_root", "user_data/acceptance/paper")))
        output_root = output_override or configured_output
        if not runtime_path.is_absolute():
            runtime_path = (selected.parent / runtime_path).resolve()
        if output_override is not None and not output_root.is_absolute():
            output_root = output_root.resolve()
        elif not output_root.is_absolute():
            output_root = (selected.parent / output_root).resolve()
        values["runtime_config_path"] = runtime_path
        values["output_root"] = output_root
        return cls(**values)
