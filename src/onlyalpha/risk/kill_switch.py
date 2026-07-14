"""Internal Kill Switch state; Cluster receives only a read-only projection."""

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId
from onlyalpha.risk.enums import OnlyKillSwitchState


@dataclass(frozen=True, slots=True)
class OnlyKillSwitchReason:
    code: str
    message: str


class OnlyRiskKillSwitch:
    def __init__(self) -> None:
        self._system = OnlyKillSwitchState.INACTIVE
        self._runtime = OnlyKillSwitchState.INACTIVE
        self._accounts: dict[OnlyAccountId, OnlyKillSwitchState] = {}
        self._clusters: dict[OnlyClusterId, OnlyKillSwitchState] = {}

    def set_system(self, state: OnlyKillSwitchState) -> None:
        self._system = state

    def set_runtime(self, state: OnlyKillSwitchState) -> None:
        self._runtime = state

    def set_account(self, account_id: OnlyAccountId, state: OnlyKillSwitchState) -> None:
        self._accounts[account_id] = state

    def set_cluster(self, cluster_id: OnlyClusterId, state: OnlyKillSwitchState) -> None:
        self._clusters[cluster_id] = state

    def is_active(self, cluster_id: OnlyClusterId, account_id: OnlyAccountId) -> bool:
        return any(
            state is OnlyKillSwitchState.ACTIVE
            for state in (
                self._system,
                self._runtime,
                self._accounts.get(account_id, OnlyKillSwitchState.INACTIVE),
                self._clusters.get(cluster_id, OnlyKillSwitchState.INACTIVE),
            )
        )
