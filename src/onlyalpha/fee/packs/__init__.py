"""Explicit fee packs used by Runtime assembly and generic conformance."""

from dataclasses import dataclass

from onlyalpha.fee.models import only_fee_fingerprint
from onlyalpha.fee.packs.generic_crypto_spot import only_generic_crypto_spot_fee_pack
from onlyalpha.fee.packs.generic_margin_futures import only_generic_margin_futures_fee_pack
from onlyalpha.fee.packs.generic_t0_cash import only_generic_t0_cash_fee_pack
from onlyalpha.fee.schedules import OnlyBrokerFeeSchedule, OnlyMarketFeeSchedule


@dataclass(frozen=True, slots=True)
class OnlyFeePolicyPack:
    pack_id: str
    pack_version: str
    compatible_market_profiles: tuple[str, ...]
    market_schedules: tuple[OnlyMarketFeeSchedule, ...]
    broker_schedules: tuple[OnlyBrokerFeeSchedule, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.pack_id.strip() or not self.pack_version.strip() or not self.compatible_market_profiles:
            raise ValueError("fee policy pack identity/compatibility cannot be empty")
        if self.fingerprint != only_fee_fingerprint(self.authority_payload()):
            raise ValueError("FEE_POLICY_PACK_FINGERPRINT_CONFLICT")

    @classmethod
    def create(
        cls,
        *,
        pack_id: str,
        pack_version: str,
        compatible_market_profiles: tuple[str, ...],
        market_schedules: tuple[OnlyMarketFeeSchedule, ...],
        broker_schedules: tuple[OnlyBrokerFeeSchedule, ...] = (),
    ) -> "OnlyFeePolicyPack":
        markets = tuple(sorted(market_schedules, key=lambda value: (value.schedule_id, value.version)))
        brokers = tuple(sorted(broker_schedules, key=lambda value: (value.schedule_id, value.version)))
        profiles = tuple(sorted(compatible_market_profiles))
        payload = (
            pack_id,
            pack_version,
            profiles,
            tuple(item.fingerprint for item in markets),
            tuple(item.fingerprint for item in brokers),
        )
        return cls(pack_id, pack_version, profiles, markets, brokers, only_fee_fingerprint(payload))

    def authority_payload(self) -> tuple[object, ...]:
        return (
            self.pack_id,
            self.pack_version,
            self.compatible_market_profiles,
            tuple(item.fingerprint for item in self.market_schedules),
            tuple(item.fingerprint for item in self.broker_schedules),
        )


class OnlyFeePolicyPackRegistry:
    def __init__(self) -> None:
        self._packs: dict[tuple[str, str], OnlyFeePolicyPack] = {}

    def register(self, pack: OnlyFeePolicyPack) -> None:
        key = (pack.pack_id, pack.pack_version)
        current = self._packs.get(key)
        if current is not None:
            if current.fingerprint != pack.fingerprint:
                raise ValueError("FEE_POLICY_PACK_FINGERPRINT_CONFLICT")
            raise ValueError("FEE_POLICY_PACK_DUPLICATE_VERSION")
        self._packs[key] = pack

    def require(self, pack_id: str, pack_version: str) -> OnlyFeePolicyPack:
        try:
            return self._packs[(pack_id, pack_version)]
        except KeyError as exc:
            raise ValueError("FEE_PACK_NOT_INSTALLED") from exc


__all__ = [
    "OnlyFeePolicyPack",
    "OnlyFeePolicyPackRegistry",
    "only_generic_crypto_spot_fee_pack",
    "only_generic_margin_futures_fee_pack",
    "only_generic_t0_cash_fee_pack",
]
