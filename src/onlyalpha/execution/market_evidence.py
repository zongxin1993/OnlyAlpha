"""Audit-only projection of compiled market identity into durable facts."""

from __future__ import annotations

from typing import TypedDict

from onlyalpha.market.runtime_rules import OnlyCompiledMarketRuleIdentity


class OnlyExecutionMarketEvidence(TypedDict):
    market_profile_id: str
    market_profile_version: str
    compiled_rule_fingerprint: str
    reference_fingerprint: str


def only_execution_market_evidence(
    identity: OnlyCompiledMarketRuleIdentity,
) -> OnlyExecutionMarketEvidence:
    """Keep market identity as trace evidence without granting permission."""

    return {
        "market_profile_id": identity.profile_id,
        "market_profile_version": identity.profile_version,
        "compiled_rule_fingerprint": identity.compiled_rules_fingerprint,
        "reference_fingerprint": identity.reference_fingerprint,
    }


__all__ = ["OnlyExecutionMarketEvidence", "only_execution_market_evidence"]
