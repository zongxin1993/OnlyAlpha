"""Stable evidence identities for Market Product composition."""

from __future__ import annotations

import re
from dataclasses import dataclass

from onlyalpha.fee.models import OnlyMarketFeePackIdentity
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.product.errors import OnlyMarketProductAuthorityConflictError

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _require_identifier(value: str, label: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a non-empty canonical identifier")


def _require_digest(value: str, label: str) -> None:
    if not _DIGEST.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True, order=True)
class OnlyMarketProductPluginId:
    value: str

    def __post_init__(self) -> None:
        _require_identifier(self.value, "Market Product plugin ID")

    def __str__(self) -> str:
        return self.value

    def canonical_identity(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class OnlyMarketProductId:
    value: str

    def __post_init__(self) -> None:
        _require_identifier(self.value, "Market Product ID")

    def __str__(self) -> str:
        return self.value

    def canonical_identity(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class OnlyMarketProductVersion:
    value: str

    def __post_init__(self) -> None:
        _require_identifier(self.value, "Market Product version")

    def __str__(self) -> str:
        return self.value

    def canonical_identity(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyMarketProductIdentity:
    product_id: OnlyMarketProductId
    product_version: OnlyMarketProductVersion

    @property
    def canonical_name(self) -> str:
        return f"{self.product_id}@{self.product_version}"

    def canonical_identity(self) -> dict[str, object]:
        return {
            "product_id": self.product_id,
            "product_version": self.product_version,
        }


@dataclass(frozen=True, slots=True)
class OnlyMarketProductAuthorityIdentity:
    authority_kind: str
    authority_id: str
    authority_version: str
    authority_fingerprint: str

    def __post_init__(self) -> None:
        _require_identifier(self.authority_kind, "authority kind")
        _require_identifier(self.authority_id, "authority ID")
        _require_identifier(self.authority_version, "authority version")
        _require_digest(self.authority_fingerprint, "authority fingerprint")

    def canonical_identity(self) -> dict[str, str]:
        return {
            "authority_fingerprint": self.authority_fingerprint,
            "authority_id": self.authority_id,
            "authority_kind": self.authority_kind,
            "authority_version": self.authority_version,
        }

    @property
    def version_key(self) -> tuple[str, str, str]:
        return (self.authority_kind, self.authority_id, self.authority_version)


@dataclass(frozen=True, slots=True)
class OnlyMarketProductCompositionIdentity:
    product_identity: OnlyMarketProductIdentity
    reference_authority: OnlyMarketProductAuthorityIdentity
    policy_compiler: OnlyMarketProductAuthorityIdentity
    market_fee_pack: OnlyMarketFeePackIdentity
    effective_config_fingerprint: str
    effective_trading_profile_fingerprint: str | None
    fingerprint: str

    def __post_init__(self) -> None:
        _require_digest(self.effective_config_fingerprint, "effective config fingerprint")
        if self.effective_trading_profile_fingerprint is not None:
            _require_digest(self.effective_trading_profile_fingerprint, "effective trading profile fingerprint")
        _require_digest(self.fingerprint, "composition fingerprint")
        expected = only_identity_fingerprint(self.effective_authority_payload())
        if self.fingerprint != expected:
            raise OnlyMarketProductAuthorityConflictError(
                "MARKET_PRODUCT_COMPOSITION_IDENTITY_CONFLICT",
                "composition fingerprint does not match effective authorities",
            )

    @classmethod
    def create(
        cls,
        *,
        product_identity: OnlyMarketProductIdentity,
        reference_authority: OnlyMarketProductAuthorityIdentity,
        policy_compiler: OnlyMarketProductAuthorityIdentity,
        market_fee_pack: OnlyMarketFeePackIdentity,
        effective_config_fingerprint: str,
        effective_trading_profile_fingerprint: str | None = None,
    ) -> OnlyMarketProductCompositionIdentity:
        payload = (
            product_identity,
            reference_authority,
            policy_compiler,
            market_fee_pack,
            effective_config_fingerprint,
            effective_trading_profile_fingerprint,
        )
        return cls(
            product_identity,
            reference_authority,
            policy_compiler,
            market_fee_pack,
            effective_config_fingerprint,
            effective_trading_profile_fingerprint,
            only_identity_fingerprint(payload),
        )

    def effective_authority_payload(self) -> tuple[object, ...]:
        return (
            self.product_identity,
            self.reference_authority,
            self.policy_compiler,
            self.market_fee_pack,
            self.effective_config_fingerprint,
            self.effective_trading_profile_fingerprint,
        )

    def canonical_identity(self) -> dict[str, object]:
        return {
            "effective_config_fingerprint": self.effective_config_fingerprint,
            "effective_trading_profile_fingerprint": self.effective_trading_profile_fingerprint,
            "market_fee_pack": self.market_fee_pack,
            "policy_compiler": self.policy_compiler,
            "product_identity": self.product_identity,
            "reference_authority": self.reference_authority,
        }


__all__ = [name for name in globals() if name.startswith("Only")]
