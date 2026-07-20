"""Strict MiniQMT configuration."""

from dataclasses import dataclass
from pathlib import Path

from onlyalpha.cache.historical.models import OnlyCachePolicy

from .errors import OnlyMiniQmtError

DEFAULT_USERDATA_MINI_PATH = Path(r"C:\国金证券QMT交易端\userdata_mini")


@dataclass(frozen=True, slots=True)
class OnlyMiniQmtConfig:
    userdata_mini_path: Path = DEFAULT_USERDATA_MINI_PATH
    account_id: str = ""
    reconnect_max_attempts: int = 5
    reconnect_initial_delay: float = 0.25
    queue_capacity: int = 4096
    cache_policy: OnlyCachePolicy = OnlyCachePolicy.PREFER_CACHE

    @classmethod
    def parse(cls, extensions: object) -> "OnlyMiniQmtConfig":
        if not isinstance(extensions, dict):
            raise OnlyMiniQmtError(
                "MINIQMT_CONFIG_INVALID", "extensions must be a mapping"
            )
        allowed = {
            "userdata_mini_path",
            "account_id",
            "reconnect_max_attempts",
            "reconnect_initial_delay",
            "queue_capacity",
            "cache_policy",
        }
        unknown = set(extensions) - allowed
        if unknown:
            raise OnlyMiniQmtError(
                "MINIQMT_CONFIG_INVALID", f"unknown fields: {sorted(unknown)}"
            )
        return cls(
            userdata_mini_path=Path(
                str(extensions.get("userdata_mini_path", DEFAULT_USERDATA_MINI_PATH))
            ),
            account_id=str(extensions.get("account_id", "")),
            reconnect_max_attempts=int(extensions.get("reconnect_max_attempts", 5)),
            reconnect_initial_delay=float(
                extensions.get("reconnect_initial_delay", 0.25)
            ),
            queue_capacity=int(extensions.get("queue_capacity", 4096)),
            cache_policy=OnlyCachePolicy(
                str(extensions.get("cache_policy", "prefer_cache"))
            ),
        )

    def require_path(self) -> Path:
        if not self.userdata_mini_path.is_dir():
            raise OnlyMiniQmtError(
                "MINIQMT_PATH_NOT_FOUND",
                f"MiniQMT path not found: {self.userdata_mini_path}",
            )
        return self.userdata_mini_path
