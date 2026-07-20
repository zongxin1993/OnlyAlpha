from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyOrderRequestId
from onlyalpha.domain.time import OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyMacdSignal:
    sequence: int
    signal_type: str
    ts_event: OnlyTimestamp
    dif: str
    dea: str
    order_request_id: OnlyOrderRequestId | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "signal_type": self.signal_type,
            "ts_event_ns": self.ts_event.unix_nanos,
            "dif": self.dif,
            "dea": self.dea,
            "order_request_id": None
            if self.order_request_id is None
            else str(self.order_request_id),
        }
