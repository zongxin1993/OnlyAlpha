from __future__ import annotations

import os
from dataclasses import dataclass, field

from onlyalpha.cache.historical.models import OnlyCachePolicy
from onlyalpha.domain.enums import OnlyAdjustmentType

from .errors import OnlyTushareError


@dataclass(frozen=True, slots=True)
class OnlyTushareConfig:
    token_env: str = "ONLYALPHA_TUSHARE_TOKEN"
    token: str | None = field(default=None, repr=False)
    frequency: str = "1d"
    adjustment: OnlyAdjustmentType = OnlyAdjustmentType.RAW
    cache_policy: OnlyCachePolicy = OnlyCachePolicy.PREFER_CACHE
    strict_validation: bool = True

    @classmethod
    def parse(cls, extensions: object) -> OnlyTushareConfig:
        if not isinstance(extensions, dict):
            raise OnlyTushareError("TUSHARE_CONFIG_INVALID", "extensions must be a mapping")
        allowed = {
            "token_env",
            "token",
            "frequency",
            "adjustment",
            "cache_policy",
            "strict_validation",
            "mode",
        }
        unknown = set(extensions) - allowed
        if unknown:
            raise OnlyTushareError("TUSHARE_CONFIG_INVALID", f"unknown fields: {sorted(unknown)}")
        if extensions.get("mode", "historical") != "historical":
            raise OnlyTushareError("TUSHARE_CONFIG_INVALID", "only historical mode is supported")
        adjustment = {
            "none": OnlyAdjustmentType.RAW,
            "qfq": OnlyAdjustmentType.FORWARD,
            "hfq": OnlyAdjustmentType.BACKWARD,
        }.get(str(extensions.get("adjustment", "none")).lower())
        if adjustment is None:
            raise OnlyTushareError("TUSHARE_CONFIG_INVALID", "adjustment must be none, qfq, or hfq")
        frequency = str(extensions.get("frequency", "1d")).lower()
        if frequency != "1d":
            raise OnlyTushareError("TUSHARE_UNSUPPORTED_BAR_TYPE", "only daily Bars are supported")
        token = extensions.get("token")
        return cls(
            token_env=str(extensions.get("token_env", "ONLYALPHA_TUSHARE_TOKEN")),
            token=None if token is None else str(token).strip(),
            frequency=frequency,
            adjustment=adjustment,
            cache_policy=OnlyCachePolicy(str(extensions.get("cache_policy", "prefer_cache"))),
            strict_validation=bool(extensions.get("strict_validation", True)),
        )

    def resolve_token(self) -> str:
        value = os.environ.get(self.token_env)
        token = value.strip() if value is not None else (self.token or "").strip()
        if not token:
            raise OnlyTushareError("TUSHARE_TOKEN_MISSING", "Tushare credential is not configured")
        return token
