"""Presentation metadata carried by an exact Calculation registration."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


@dataclass(frozen=True, slots=True)
class OnlyChartStudySeries:
    output_name: str
    label: str
    kind: Literal["LINE", "HISTOGRAM"]
    unit: Literal["PRICE", "RATIO", "VOLUME", "SCALAR"]
    color: str
    default_visible: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "output_name": self.output_name,
            "label": self.label,
            "kind": self.kind,
            "unit": self.unit,
            "color": self.color,
            "default_visible": self.default_visible,
        }


@dataclass(frozen=True, slots=True)
class OnlyChartStudySupport:
    display_name: str
    category: str
    default_parameters: Mapping[str, object]
    series: tuple[OnlyChartStudySeries, ...]
    placement: Literal["PRICE_OVERLAY", "SEPARATE_PANE"]
    fill: tuple[str, str] | None = None
    preview_supported: bool = True
    default_variant: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "default_parameters", MappingProxyType(dict(self.default_parameters)))

    def to_dict(self) -> dict[str, object]:
        return {
            "display_name": self.display_name,
            "category": self.category,
            "default_parameters": dict(self.default_parameters),
            "series": [item.to_dict() for item in self.series],
            "placement": self.placement,
            "fill": None if self.fill is None else list(self.fill),
            "preview_supported": self.preview_supported,
            "default_variant": self.default_variant,
        }
