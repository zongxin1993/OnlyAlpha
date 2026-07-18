"""Stable OnlyAlpha plugin API version contract."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class OnlyPluginApiVersion:
    major: int
    minor: int

    def __post_init__(self) -> None:
        if self.major < 0 or self.minor < 0:
            raise ValueError("plugin API version components must be non-negative")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


ONLYALPHA_PLUGIN_API_VERSION = OnlyPluginApiVersion(major=1, minor=0)
