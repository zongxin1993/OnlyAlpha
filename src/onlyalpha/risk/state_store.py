"""Runtime-local in-memory Risk state and deterministic version storage."""

from collections.abc import Hashable
from typing import Protocol

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderRequestId
from onlyalpha.risk.decisions import OnlyRiskDecision
from onlyalpha.risk.snapshots import OnlyRiskSnapshot


class OnlyRiskStateStore(Protocol):
    def next_snapshot_version(self, cluster_id: OnlyClusterId) -> int: ...

    def save_snapshot(self, snapshot: OnlyRiskSnapshot) -> None: ...

    def get_snapshot(self, cluster_id: OnlyClusterId) -> OnlyRiskSnapshot | None: ...


class OnlyInMemoryRiskStateStore(OnlyRiskStateStore):
    def __init__(self) -> None:
        self._snapshots: dict[OnlyClusterId, OnlyRiskSnapshot] = {}
        self._snapshot_versions: dict[OnlyClusterId, int] = {}
        self._rejection_counts: dict[OnlyClusterId, int] = {}
        self._decisions: dict[tuple[OnlyClusterId, OnlyAccountId, OnlyOrderRequestId], OnlyRiskDecision] = {}
        self._rule_state: dict[tuple[OnlyClusterId, Hashable], object] = {}

    def next_snapshot_version(self, cluster_id: OnlyClusterId) -> int:
        version = self._snapshot_versions.get(cluster_id, 0) + 1
        self._snapshot_versions[cluster_id] = version
        return version

    def save_snapshot(self, snapshot: OnlyRiskSnapshot) -> None:
        current = self._snapshots.get(snapshot.cluster_id)
        if current is not None and snapshot.version <= current.version:
            raise ValueError("Risk Snapshot version must increase")
        self._snapshots[snapshot.cluster_id] = snapshot

    def get_snapshot(self, cluster_id: OnlyClusterId) -> OnlyRiskSnapshot | None:
        return self._snapshots.get(cluster_id)

    def remove_cluster(self, cluster_id: OnlyClusterId) -> None:
        self._snapshots.pop(cluster_id, None)
        self._snapshot_versions.pop(cluster_id, None)
        self._rejection_counts.pop(cluster_id, None)
        for decision_key in tuple(self._decisions):
            if decision_key[0] == cluster_id:
                self._decisions.pop(decision_key)
        for state_key in tuple(self._rule_state):
            if state_key[0] == cluster_id:
                self._rule_state.pop(state_key)

    def record_rejection(self, cluster_id: OnlyClusterId) -> int:
        count = self._rejection_counts.get(cluster_id, 0) + 1
        self._rejection_counts[cluster_id] = count
        return count

    def rejection_count(self, cluster_id: OnlyClusterId) -> int:
        return self._rejection_counts.get(cluster_id, 0)

    def get_decision(
        self,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        request_id: OnlyOrderRequestId,
    ) -> OnlyRiskDecision | None:
        return self._decisions.get((cluster_id, account_id, request_id))

    def save_decision(
        self,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        request_id: OnlyOrderRequestId,
        decision: OnlyRiskDecision,
    ) -> None:
        self._decisions.setdefault((cluster_id, account_id, request_id), decision)

    def get_rule_state(self, cluster_id: OnlyClusterId, key: Hashable) -> object | None:
        return self._rule_state.get((cluster_id, key))

    def set_rule_state(self, cluster_id: OnlyClusterId, key: Hashable, value: object) -> None:
        self._rule_state[(cluster_id, key)] = value
