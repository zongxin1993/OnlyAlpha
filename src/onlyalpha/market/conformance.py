"""Conformance-pack identities and capability coverage gates."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.market.models import OnlyMarketProfileId
from onlyalpha.market.registry import OnlyMarketCapabilitySet, OnlyMarketProfileStatus


@dataclass(frozen=True, slots=True)
class OnlyMarketConformanceScenario:
    scenario_id: str
    version: str
    capability: str
    expected_unsupported: bool = False


@dataclass(frozen=True, slots=True)
class OnlyMarketConformancePack:
    pack_id: str
    profile_id: OnlyMarketProfileId
    scenarios: tuple[OnlyMarketConformanceScenario, ...]

    @property
    def covered_capabilities(self) -> frozenset[str]:
        return frozenset(item.capability for item in self.scenarios if not item.expected_unsupported)


class OnlyMarketConformanceRegistry:
    def __init__(self) -> None:
        self._packs: dict[str, OnlyMarketConformancePack] = {}

    def register(self, pack: OnlyMarketConformancePack) -> None:
        if pack.pack_id in self._packs:
            raise ValueError(f"conformance pack already registered: {pack.pack_id}")
        if not pack.scenarios:
            raise ValueError("conformance pack must contain scenarios")
        self._packs[pack.pack_id] = pack

    def get(self, pack_id: str) -> OnlyMarketConformancePack:
        try:
            return self._packs[pack_id]
        except KeyError as exc:
            raise ValueError(f"unknown conformance pack: {pack_id}") from exc

    def validate_capabilities(
        self,
        *,
        status: OnlyMarketProfileStatus,
        pack_id: str | None,
        capabilities: OnlyMarketCapabilitySet,
    ) -> None:
        if status is not OnlyMarketProfileStatus.STABLE:
            return
        if pack_id is None:
            raise ValueError("stable profile requires conformance pack")
        missing = sorted(set(capabilities.enabled) - self.get(pack_id).covered_capabilities)
        if missing:
            raise ValueError(f"stable profile capabilities lack conformance scenarios: {', '.join(missing)}")
