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

    def capture_checkpoint(self) -> object:
        return {
            "records": [
                {
                    "cluster_id": item.cluster_id,
                    "confidence": None if item.confidence is None else str(item.confidence),
                    "factor_id": item.factor_id,
                    "instrument_id": item.instrument_id,
                    "payload": dict(item.payload),
                    "related_order_request_id": item.related_order_request_id,
                    "score": None if item.score is None else str(item.score),
                    "sequence": item.sequence,
                    "signal_id": item.signal_id,
                    "signal_type": item.signal_type,
                    "strategy_id": item.strategy_id,
                    "trading_day": item.trading_day.isoformat(),
                    "ts_event": item.ts_event.isoformat(),
                }
                for item in self._records
            ],
            "sealed": self._sealed,
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Strategy result checkpoint must be an object")
        records: list[OnlySignalResultRecord] = []
        for item in payload["records"]:
            if not isinstance(item, dict):
                raise ValueError("Strategy result checkpoint record must be an object")
            records.append(
                OnlySignalResultRecord(
                    sequence=int(item["sequence"]),
                    signal_id=str(item["signal_id"]),
                    cluster_id=str(item["cluster_id"]),
                    strategy_id=str(item["strategy_id"]),
                    factor_id=None if item["factor_id"] is None else str(item["factor_id"]),
                    instrument_id=str(item["instrument_id"]),
                    signal_type=str(item["signal_type"]),
                    ts_event=datetime.fromisoformat(str(item["ts_event"])),
                    trading_day=date.fromisoformat(str(item["trading_day"])),
                    score=None if item["score"] is None else Decimal(str(item["score"])),
                    confidence=None if item["confidence"] is None else Decimal(str(item["confidence"])),
                    related_order_request_id=(
                        None if item["related_order_request_id"] is None else str(item["related_order_request_id"])
                    ),
                    payload=item["payload"],
                )
            )
        self._records = records
        self._sealed = bool(payload["sealed"])
