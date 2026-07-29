"""Exact cursor-based Backtest replay for one causal execution recovery session."""

from __future__ import annotations

from collections.abc import Callable

from onlyalpha.data.enums import OnlyMarketDataProcessingStatus
from onlyalpha.data.models import (
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataStream,
    OnlyHistoricalReplayConfig,
)
from onlyalpha.data.ports import OnlyHistoricalDataSource
from onlyalpha.data.registry import OnlyMarketDataSourceRegistry
from onlyalpha.data.replay import OnlyHistoricalReplayService
from onlyalpha.execution import OnlyExecutionRecoverySession
from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint


class OnlyBacktestRecoveryReplayService:
    def __init__(
        self,
        *,
        source: OnlyHistoricalDataSource | None,
        request: OnlyHistoricalBarRequest | None,
        source_registry: OnlyMarketDataSourceRegistry,
        replay: OnlyHistoricalReplayService,
        activate: Callable[[OnlyExecutionRecoverySession], None],
        deactivate: Callable[[], None],
    ) -> None:
        self._source = source
        self._request = request
        self._source_registry = source_registry
        self._replay = replay
        self._activate = activate
        self._deactivate = deactivate

    def run(self, checkpoint: OnlyRuntimeCheckpoint, session: OnlyExecutionRecoverySession) -> int:
        if self._source is None or self._request is None:
            raise RuntimeError("Recovery replay source is unavailable")
        if not self._source_registry.contains(self._source.source_id):
            self._source_registry.register(self._source)
        stream = self._source.load_bars(self._request)
        cursor = checkpoint.header.replay_cursor
        if cursor.last_update_id is None:
            remaining = stream.records
        else:
            matched = tuple(
                index
                for index, item in enumerate(stream.records)
                if item.update_id == cursor.last_update_id
                and int(item.source_sequence) == cursor.last_source_sequence
                and item.source_id == cursor.source_id
                and item.data_version == cursor.data_version
            )
            if len(matched) != 1:
                raise RuntimeError("recovery replay cursor identity is absent or ambiguous")
            remaining = stream.records[matched[0] + 1 :]
        processed = 0
        resolved = False
        self._activate(session)
        try:
            for record in remaining:
                replay_cursor = self._replay.prepare(
                    OnlyHistoricalReplayConfig(
                        (OnlyHistoricalDataStream((record,), 1),),
                        source_priority=(self._source.source_id,),
                    )
                )
                result = self._replay.run(replay_cursor)
                if result.failed or result.rejected:
                    failures = tuple(
                        (
                            event.result.status.value,
                            event.result.validation.reasons,
                            None
                            if event.result.failure is None
                            else (event.result.failure.error_type, event.result.failure.message),
                        )
                        for event in result.events
                        if event.result.status
                        in {OnlyMarketDataProcessingStatus.FAILED, OnlyMarketDataProcessingStatus.REJECTED}
                    )
                    raise RuntimeError(f"recovery MarketData replay failed: {failures}")
                processed += result.processed
                if session.complete:
                    session.complete_boundary()
                    resolved = True
                    break
        finally:
            self._deactivate()
        if not resolved:
            raise RuntimeError("recovery replay did not resolve every transaction-tail Broker update")
        return processed
