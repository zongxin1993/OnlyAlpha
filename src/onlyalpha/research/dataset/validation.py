"""Dataset-level invariants stricter than acquisition cache validation."""

from __future__ import annotations

from onlyalpha.domain.market import OnlyBar

from .definition import OnlyResearchDatasetDefinition
from .identity import only_canonical_bar_key


class OnlyResearchDatasetError(ValueError):
    pass


def only_validate_dataset_bars(definition: OnlyResearchDatasetDefinition, bars: tuple[OnlyBar, ...]) -> None:
    allowed = set(definition.instruments)
    seen: dict[tuple[object, object, object], OnlyBar] = {}
    for bar in bars:
        if bar.instrument_id not in allowed:
            raise OnlyResearchDatasetError("DATASET_INPUT_INVALID: unknown instrument")
        if bar.bar_type.specification != definition.bar_specification:
            raise OnlyResearchDatasetError("DATASET_INPUT_INVALID: Bar specification mismatch")
        if bar.bar_type.aggregation_source is not definition.aggregation_source:
            raise OnlyResearchDatasetError("DATASET_INPUT_INVALID: aggregation source mismatch")
        if bar.adjustment_type is not definition.adjustment_type:
            raise OnlyResearchDatasetError("DATASET_INPUT_INVALID: adjustment mismatch")
        if not bar.is_closed:
            raise OnlyResearchDatasetError("DATASET_INPUT_INVALID: open Bar")
        if not definition.time_range.contains(bar.ts_event):
            raise OnlyResearchDatasetError("DATASET_INPUT_INVALID: Bar outside requested range")
        key = (bar.instrument_id, bar.bar_start, bar.bar_end)
        previous = seen.get(key)
        if previous is not None:
            detail = "duplicate" if previous == bar else "conflicting duplicate"
            raise OnlyResearchDatasetError(f"DATASET_CONTENT_CONFLICT: {detail} logical Bar")
        seen[key] = bar
        only_canonical_bar_key(bar)
