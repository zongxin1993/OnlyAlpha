from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from onlyalpha_market_binance_spot.reference import OnlyBinanceSpotReferenceAuthority

from onlyalpha.plugin.api import only_identity_fingerprint
from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment
from onlyalpha_plugin_binance.spot.reference.client import OnlyBinanceSpotReferenceClient
from onlyalpha_plugin_binance.spot.reference.normalize import only_normalize_binance_spot_reference

_CAPTURE_SCHEMA_VERSION = 1
_PARSER_CONTRACT_VERSION = "BINANCE_SPOT_REFERENCE_NORMALIZER@2"


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotRawEvidence:
    endpoint_id: str
    request_parameters: tuple[tuple[str, str], ...]
    raw_bytes: bytes
    raw_sha256: str

    @classmethod
    def create(
        cls,
        endpoint_id: str,
        request_parameters: tuple[tuple[str, str], ...],
        raw_bytes: bytes,
    ) -> OnlyBinanceSpotRawEvidence:
        return cls(endpoint_id, tuple(sorted(request_parameters)), raw_bytes, sha256(raw_bytes).hexdigest())


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotCaptureProvenance:
    schema_version: int
    provider: str
    product: str
    environment: OnlyBinanceEnvironment
    captured_at_utc: datetime
    parser_contract_version: str
    requested_symbols: tuple[str, ...]
    server_time: int | None


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotReferenceCapture:
    provenance: OnlyBinanceSpotCaptureProvenance
    evidence: tuple[OnlyBinanceSpotRawEvidence, ...]
    capture_fingerprint: str
    authority: OnlyBinanceSpotReferenceAuthority

    @classmethod
    def create(
        cls,
        exchange_info: bytes,
        execution_rules: bytes,
        captured_at: datetime,
        *,
        environment: OnlyBinanceEnvironment = OnlyBinanceEnvironment.LIVE,
        requested_symbols: tuple[str, ...] | None = None,
        parser_contract_version: str = _PARSER_CONTRACT_VERSION,
    ) -> OnlyBinanceSpotReferenceCapture:
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("BINANCE_SPOT_CAPTURED_AT_UTC_REQUIRED")
        observed_at = captured_at.astimezone(UTC)
        hashes = (sha256(exchange_info).hexdigest(), sha256(execution_rules).hexdigest())
        authority = only_normalize_binance_spot_reference(
            exchange_info, execution_rules, observed_at=observed_at, raw_fingerprints=hashes
        )
        symbols = tuple(sorted(set(requested_symbols or tuple(item.raw_symbol for item in authority.references))))
        parameter = (("symbols", json.dumps(symbols, separators=(",", ":"))),)
        evidence = (
            OnlyBinanceSpotRawEvidence.create("/api/v3/exchangeInfo", parameter, exchange_info),
            OnlyBinanceSpotRawEvidence.create("/api/v3/executionRules", parameter, execution_rules),
        )
        provenance = OnlyBinanceSpotCaptureProvenance(
            _CAPTURE_SCHEMA_VERSION,
            "BINANCE",
            "SPOT",
            environment,
            observed_at,
            parser_contract_version,
            symbols,
            _server_time(exchange_info),
        )
        fingerprint = only_identity_fingerprint(
            (
                provenance.schema_version,
                provenance.provider,
                provenance.product,
                provenance.environment,
                provenance.captured_at_utc,
                provenance.parser_contract_version,
                provenance.requested_symbols,
                tuple((item.endpoint_id, item.request_parameters, item.raw_sha256) for item in evidence),
            )
        )
        return cls(provenance, evidence, fingerprint, authority)

    @property
    def captured_at(self) -> datetime:
        return self.provenance.captured_at_utc

    @property
    def exchange_info(self) -> bytes:
        return self.evidence[0].raw_bytes

    @property
    def execution_rules(self) -> bytes:
        return self.evidence[1].raw_bytes

    @property
    def exchange_info_fingerprint(self) -> str:
        return self.evidence[0].raw_sha256

    @property
    def execution_rules_fingerprint(self) -> str:
        return self.evidence[1].raw_sha256


def only_capture_binance_spot_reference(
    client: OnlyBinanceSpotReferenceClient,
    symbols: tuple[str, ...],
    *,
    environment: OnlyBinanceEnvironment = OnlyBinanceEnvironment.LIVE,
    captured_at: datetime | None = None,
) -> OnlyBinanceSpotReferenceCapture:
    return OnlyBinanceSpotReferenceCapture.create(
        client.exchange_info(symbols),
        client.execution_rules(symbols),
        captured_at or datetime.now(UTC),
        environment=environment,
        requested_symbols=symbols,
    )


def _server_time(exchange_info: bytes) -> int | None:
    value = json.loads(exchange_info).get("serverTime")
    if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValueError("BINANCE_SPOT_SERVER_TIME_INVALID")
    return value
