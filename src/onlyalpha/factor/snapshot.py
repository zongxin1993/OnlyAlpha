"""Common Factor snapshot contract."""

from abc import ABC, abstractmethod
from collections.abc import Mapping

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.factor.identifiers import OnlyFactorId


class OnlyFactorSnapshot(ABC):
    factor_id: OnlyFactorId
    ready: bool
    ts_event: OnlyTimestamp | None

    @abstractmethod
    def to_dict(self) -> Mapping[str, object]: ...
