"""Versioned Market fee-pack authority."""

from dataclasses import dataclass

from onlyalpha.fee.models import OnlyMarketFeePackIdentity, only_fee_fingerprint
from onlyalpha.fee.schedules import OnlyMarketFeeSchedule, OnlyMarketFeeScheduleRegistry


@dataclass(frozen=True, slots=True)
class OnlyMarketFeePack:
    pack_id: str
    pack_version: str
    compatible_market_profiles: tuple[str, ...]
    schedules: tuple[OnlyMarketFeeSchedule, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.pack_id.strip() or not self.pack_version.strip() or not self.compatible_market_profiles:
            raise ValueError("market fee pack identity/compatibility cannot be empty")
        registry = OnlyMarketFeeScheduleRegistry()
        for schedule in self.schedules:
            registry.register(schedule)
        if self.fingerprint != only_fee_fingerprint(self.authority_payload()):
            raise ValueError("MARKET_FEE_PACK_FINGERPRINT_CONFLICT")

    @classmethod
    def create(
        cls,
        *,
        pack_id: str,
        pack_version: str,
        compatible_market_profiles: tuple[str, ...],
        schedules: tuple[OnlyMarketFeeSchedule, ...],
    ) -> "OnlyMarketFeePack":
        ordered = tuple(sorted(schedules, key=lambda value: (value.schedule_id, value.version)))
        profiles = tuple(sorted(set(compatible_market_profiles)))
        payload = (pack_id, pack_version, profiles, tuple(item.fingerprint for item in ordered))
        return cls(pack_id, pack_version, profiles, ordered, only_fee_fingerprint(payload))

    @property
    def identity(self) -> OnlyMarketFeePackIdentity:
        return OnlyMarketFeePackIdentity(self.pack_id, self.pack_version, self.fingerprint)

    def authority_payload(self) -> tuple[object, ...]:
        return (
            self.pack_id,
            self.pack_version,
            self.compatible_market_profiles,
            tuple(item.fingerprint for item in self.schedules),
        )

    def validate_compatibility(self, market_profile_id: str) -> None:
        if market_profile_id not in self.compatible_market_profiles:
            raise ValueError("MARKET_FEE_PACK_PROFILE_INCOMPATIBLE")


class OnlyMarketFeePackRegistry:
    def __init__(self) -> None:
        self._packs: dict[tuple[str, str], OnlyMarketFeePack] = {}

    def register(self, pack: OnlyMarketFeePack) -> None:
        key = (pack.pack_id, pack.pack_version)
        current = self._packs.get(key)
        if current is not None:
            if current.fingerprint != pack.fingerprint:
                raise ValueError("MARKET_FEE_PACK_FINGERPRINT_CONFLICT")
            raise ValueError("MARKET_FEE_PACK_DUPLICATE_VERSION")
        self._packs[key] = pack

    def require(self, pack_id: str, pack_version: str) -> OnlyMarketFeePack:
        try:
            return self._packs[(pack_id, pack_version)]
        except KeyError as exc:
            raise ValueError("MARKET_FEE_PACK_NOT_INSTALLED") from exc


__all__ = ["OnlyMarketFeePack", "OnlyMarketFeePackRegistry"]
