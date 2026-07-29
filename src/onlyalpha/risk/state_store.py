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

    def restore_snapshot(self, snapshot: OnlyRiskSnapshot) -> None:
        self._snapshots[snapshot.cluster_id] = snapshot
        self._snapshot_versions[snapshot.cluster_id] = snapshot.version

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

    def capture_checkpoint(self) -> object:
        if self._rule_state:
            raise ValueError("stateful Risk rule checkpoint contracts are not declared")
        return {
            "decisions": [
                [str(cluster_id), str(account_id), str(request_id), decision.to_json()]
                for (cluster_id, account_id, request_id), decision in sorted(
                    self._decisions.items(), key=lambda item: tuple(str(part) for part in item[0])
                )
            ],
            "rejection_counts": [
                [str(cluster_id), count]
                for cluster_id, count in sorted(self._rejection_counts.items(), key=lambda item: str(item[0]))
            ],
            "snapshot_versions": [
                [str(cluster_id), version]
                for cluster_id, version in sorted(self._snapshot_versions.items(), key=lambda item: str(item[0]))
            ],
            "snapshots": [
                snapshot.to_json() for _, snapshot in sorted(self._snapshots.items(), key=lambda item: str(item[0]))
            ],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Risk state checkpoint must be an object")
        self._snapshots = {
            snapshot.cluster_id: snapshot
            for raw in payload["snapshots"]
            if (snapshot := OnlyRiskSnapshot.from_json(str(raw)))
        }
        self._snapshot_versions = {
            OnlyClusterId(str(cluster_id)): int(version) for cluster_id, version in payload["snapshot_versions"]
        }
        self._rejection_counts = {
            OnlyClusterId(str(cluster_id)): int(count) for cluster_id, count in payload["rejection_counts"]
        }
        self._decisions = {
            (
                OnlyClusterId(str(cluster_id)),
                OnlyAccountId(str(account_id)),
                OnlyOrderRequestId(str(request_id)),
            ): OnlyRiskDecision.from_json(str(raw))
            for cluster_id, account_id, request_id, raw in payload["decisions"]
        }
        self._rule_state.clear()
