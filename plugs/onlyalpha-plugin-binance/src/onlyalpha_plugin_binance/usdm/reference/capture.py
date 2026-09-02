"""Immutable raw-evidence capture for USD-M public and account-effective references."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from onlyalpha_plugin_binance_usdm import (
    OnlyBinanceUsdmAccountReferenceAuthority,
    OnlyBinanceUsdmPublicReferenceAuthority,
)

from onlyalpha.identity import only_identity_fingerprint
from onlyalpha_plugin_binance.usdm.reference.normalize import only_normalize_binance_usdm_references


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmRawEvidence:
    endpoint_id: str
    request_parameters: tuple[tuple[str, str], ...]
    raw_bytes: bytes
    raw_sha256: str

    @classmethod
    def create(
        cls, endpoint_id: str, request_parameters: tuple[tuple[str, str], ...], raw_bytes: bytes
    ) -> OnlyBinanceUsdmRawEvidence:
        return cls(endpoint_id, tuple(sorted(request_parameters)), raw_bytes, sha256(raw_bytes).hexdigest())


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmReferenceCapture:
    captured_at: datetime
    coverage_start: datetime
    coverage_end: datetime | None
    evidence: tuple[OnlyBinanceUsdmRawEvidence, ...]
    capture_fingerprint: str
    public_authority: OnlyBinanceUsdmPublicReferenceAuthority
    account_authority: OnlyBinanceUsdmAccountReferenceAuthority

    @classmethod
    def create(
        cls,
        exchange_info: bytes,
        funding_info: bytes,
        leverage_brackets: bytes,
        account_profile: bytes,
        *,
        captured_at: datetime,
        coverage_start: datetime,
        coverage_end: datetime | None = None,
    ) -> OnlyBinanceUsdmReferenceCapture:
        captured = _utc(captured_at, "BINANCE_USDM_CAPTURED_AT_UTC_REQUIRED")
        start = _utc(coverage_start, "BINANCE_USDM_COVERAGE_START_UTC_REQUIRED")
        end = None if coverage_end is None else _utc(coverage_end, "BINANCE_USDM_COVERAGE_END_UTC_REQUIRED")
        evidence = (
            OnlyBinanceUsdmRawEvidence.create("/fapi/v1/exchangeInfo", (), exchange_info),
            OnlyBinanceUsdmRawEvidence.create("/fapi/v1/fundingInfo", (), funding_info),
            OnlyBinanceUsdmRawEvidence.create("/fapi/v1/leverageBracket", (), leverage_brackets),
            OnlyBinanceUsdmRawEvidence.create("ONLYALPHA_BINANCE_USDM_ACCOUNT_PROFILE@1", (), account_profile),
        )
        fingerprints = tuple(item.raw_sha256 for item in evidence)
        public, account = only_normalize_binance_usdm_references(
            exchange_info,
            funding_info,
            leverage_brackets,
            account_profile,
            observed_at=captured,
            published_at=captured,
            coverage_start=start,
            coverage_end=end,
            raw_fingerprints=fingerprints,  # type: ignore[arg-type]
        )
        fingerprint = only_identity_fingerprint(
            (
                "BINANCE_USDM_REFERENCE_CAPTURE@2",
                captured,
                start,
                end,
                tuple((item.endpoint_id, item.request_parameters, item.raw_sha256) for item in evidence),
                public.identity,
                account.identity,
            )
        )
        return cls(captured, start, end, evidence, fingerprint, public, account)


def _utc(value: datetime, code: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(code)
    return value.astimezone(UTC)


__all__ = ["OnlyBinanceUsdmRawEvidence", "OnlyBinanceUsdmReferenceCapture"]
