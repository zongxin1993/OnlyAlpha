"""Backtest-only extension configuration parsed by the Backtest factory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.config.models import OnlyJsonMapping


@dataclass(frozen=True, slots=True)
class OnlyBacktestRuntimeExtensionConfig:
    """Backtest replay policy; no full run-document fields live here."""

    stop_on_data_error: bool = True

    @classmethod
    def from_mapping(cls, extensions: OnlyJsonMapping) -> OnlyBacktestRuntimeExtensionConfig:
        raw = extensions.get("replay", {})
        if not isinstance(raw, Mapping):
            raise ValueError("runtime.extensions.replay must be a mapping")
        value = raw.get("stop_on_data_error", True)
        if not isinstance(value, bool):
            raise ValueError("runtime.extensions.replay.stop_on_data_error must be boolean")
        return cls(value)

    def to_json(self) -> dict[str, object]:
        return {"replay": {"stop_on_data_error": self.stop_on_data_error}}
