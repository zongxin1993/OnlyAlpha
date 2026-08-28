from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from onlyalpha_market_binance_spot.reference import OnlyBinanceSpotReferenceAuthority

from onlyalpha_plugin_binance.spot.reference.client import OnlyBinanceSpotReferenceClient
from onlyalpha_plugin_binance.spot.reference.normalize import only_normalize_binance_spot_reference


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotReferenceCapture:
    exchange_info: bytes
    execution_rules: bytes
    captured_at: datetime
    exchange_info_fingerprint: str
    execution_rules_fingerprint: str
    authority: OnlyBinanceSpotReferenceAuthority

    @classmethod
    def create(
        cls, exchange_info: bytes, execution_rules: bytes, captured_at: datetime
    ) -> "OnlyBinanceSpotReferenceCapture":
        hashes = (sha256(exchange_info).hexdigest(), sha256(execution_rules).hexdigest())
        authority = only_normalize_binance_spot_reference(
            exchange_info, execution_rules, observed_at=captured_at, raw_fingerprints=hashes
        )
        return cls(exchange_info, execution_rules, captured_at.astimezone(UTC), *hashes, authority)


def only_capture_binance_spot_reference(
    client: OnlyBinanceSpotReferenceClient, symbols: tuple[str, ...], *, captured_at: datetime | None = None
) -> OnlyBinanceSpotReferenceCapture:
    return OnlyBinanceSpotReferenceCapture.create(
        client.exchange_info(symbols), client.execution_rules(symbols), captured_at or datetime.now(UTC)
    )
