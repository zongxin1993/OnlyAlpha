"""Versioned market-agnostic Backtest Product profile authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload

from .model import OnlyBacktestProfileReference

_KINDS = frozenset({"PORTFOLIO", "RISK", "EXECUTION"})


@dataclass(frozen=True, slots=True)
class OnlyBacktestProfile:
    kind: str
    reference: OnlyBacktestProfileReference
    semantics: Mapping[str, object]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.kind not in _KINDS or self.schema_version != 1:
            raise ValueError("BACKTEST_PROFILE_INVALID")
        canonical = only_canonical_payload(self.semantics)
        if not isinstance(canonical, Mapping):
            raise ValueError("BACKTEST_PROFILE_SEMANTICS_INVALID")
        object.__setattr__(self, "semantics", canonical)

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "reference": self.reference.to_dict(),
            "semantics": self.semantics,
        }


class OnlyBacktestProfileRegistry:
    def __init__(self, profiles: tuple[OnlyBacktestProfile, ...] = ()) -> None:
        self._profiles: dict[tuple[str, OnlyBacktestProfileReference], OnlyBacktestProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: OnlyBacktestProfile) -> None:
        key = (profile.kind, profile.reference)
        current = self._profiles.get(key)
        if current is not None and current != profile:
            raise ValueError("BACKTEST_PROFILE_VERSION_CONFLICT")
        self._profiles[key] = profile

    def resolve_profile(self, kind: str, reference: OnlyBacktestProfileReference) -> OnlyBacktestProfile:
        try:
            profile = self._profiles[(kind, reference)]
        except KeyError as exc:
            raise ValueError("BACKTEST_PROFILE_NOT_FOUND") from exc
        if profile.fingerprint != only_canonical_fingerprint(profile.to_dict()):
            raise ValueError("BACKTEST_PROFILE_CORRUPT")
        return profile


def only_default_backtest_profile_registry() -> OnlyBacktestProfileRegistry:
    return OnlyBacktestProfileRegistry(
        (
            OnlyBacktestProfile(
                "PORTFOLIO",
                OnlyBacktestProfileReference("fixed-capital", "1"),
                {"allocation_model": "FIXED_CAPITAL"},
            ),
            OnlyBacktestProfile(
                "RISK",
                OnlyBacktestProfileReference("default-risk", "1"),
                {"mandatory_system_rules": True, "optional_rules": []},
            ),
            OnlyBacktestProfile(
                "EXECUTION",
                OnlyBacktestProfileReference("virtual-next-bar", "1"),
                {"broker_model": "VIRTUAL", "matching_policy": "NEXT_BAR"},
            ),
            OnlyBacktestProfile(
                "EXECUTION",
                OnlyBacktestProfileReference("virtual-next-bar", "2"),
                {
                    "broker_model": "VIRTUAL",
                    "matching": {"type": "NEXT_BAR"},
                    "slippage": {"type": "NONE"},
                    "latency": {
                        "submit_ns": 0,
                        "acceptance_ns": 0,
                        "fill_ns": 0,
                        "cancel_ns": 0,
                        "query_ns": 0,
                    },
                    "broker_fee_contract": {
                        "contract_id": "VIRTUAL_SIMULATION_ZERO_BROKER_FEES",
                        "contract_version": "1",
                    },
                    "fee_reconciliation_policy": {
                        "policy_id": "STANDARD_FEE_RECONCILIATION",
                        "policy_version": "1",
                    },
                },
            ),
        )
    )


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
