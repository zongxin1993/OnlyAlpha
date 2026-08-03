"""Thread-safe latest-observation authority."""

from threading import Lock

from onlyalpha.domain.identifiers import OnlyClusterId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBarType

from .models import OnlyMarketObservationSnapshot


class OnlyLatestObservationStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[tuple[str, str, str, OnlyBarType], OnlyMarketObservationSnapshot] = {}

    def put(self, snapshot: OnlyMarketObservationSnapshot) -> None:
        key = (
            str(snapshot.runtime_id),
            str(snapshot.cluster_id),
            str(snapshot.instrument_id),
            snapshot.bar_type,
        )
        with self._lock:
            current = self._items.get(key)
            if current is None or snapshot.latest_bar_end.unix_nanos >= current.latest_bar_end.unix_nanos:
                self._items[key] = snapshot

    def latest(
        self,
        runtime_id: OnlyRuntimeId,
        cluster_id: OnlyClusterId,
        instrument_id: OnlyInstrumentId,
        bar_type: OnlyBarType,
    ) -> OnlyMarketObservationSnapshot | None:
        with self._lock:
            return self._items.get((str(runtime_id), str(cluster_id), str(instrument_id), bar_type))

    def list_runtime(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyMarketObservationSnapshot, ...]:
        with self._lock:
            return tuple(
                value
                for key, value in sorted(self._items.items(), key=lambda item: str(item[0]))
                if key[0] == str(runtime_id)
            )
