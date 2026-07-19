"""Restricted Strategy-facing standard result recording API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from onlyalpha.domain.time import only_require_utc
from onlyalpha.result.records import OnlySignalResultRecord


class OnlyStrategyResultRecorder:
    __slots__ = ("_cluster_id", "_records", "_sealed", "_strategy_id")

    def __init__(self, cluster_id: str, strategy_id: str) -> None:
        self._cluster_id = cluster_id
        self._strategy_id = strategy_id
        self._records: list[OnlySignalResultRecord] = []
        self._sealed = False

    def record_signal(
        self,
        *,
        signal_type: str,
        instrument_id: str,
        ts_event: datetime,
        trading_day: date,
        factor_id: str | None = None,
        score: Decimal | None = None,
        confidence: Decimal | None = None,
        related_order_request_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> OnlySignalResultRecord:
        if self._sealed:
            raise RuntimeError("strategy result recorder is sealed")
        only_require_utc(ts_event, "signal ts_event")
        sequence = len(self._records) + 1
        stable_key = (
            f"{self._cluster_id}:{self._strategy_id}:{sequence}:{signal_type}:{instrument_id}:{ts_event.isoformat()}"
        )
        record = OnlySignalResultRecord(
            sequence=sequence,
            signal_id=str(uuid5(NAMESPACE_URL, stable_key)),
            cluster_id=self._cluster_id,
            strategy_id=self._strategy_id,
            factor_id=factor_id,
            instrument_id=instrument_id,
            signal_type=signal_type,
            ts_event=ts_event,
            trading_day=trading_day,
            score=score,
            confidence=confidence,
            related_order_request_id=related_order_request_id,
            payload={} if payload is None else payload,
        )
        self._records.append(record)
        return record

    def snapshot(self) -> tuple[OnlySignalResultRecord, ...]:
        return tuple(self._records)

    def seal(self) -> tuple[OnlySignalResultRecord, ...]:
        self._sealed = True
        return self.snapshot()
