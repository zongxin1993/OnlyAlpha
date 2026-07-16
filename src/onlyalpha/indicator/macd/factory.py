from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.factory import OnlyIndicatorCreateRequest
from onlyalpha.indicator.identifiers import MACD, OnlyIndicatorTypeId
from onlyalpha.indicator.macd.config import OnlyMacdIndicatorConfig
from onlyalpha.indicator.macd.indicator import OnlyMacdIndicator
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot


class OnlyMacdIndicatorFactory:
    @property
    def indicator_type(self) -> OnlyIndicatorTypeId:
        return MACD

    def create(self, request: OnlyIndicatorCreateRequest) -> OnlyBarIndicator[OnlyIndicatorSnapshot]:
        return OnlyMacdIndicator(
            OnlyMacdIndicatorConfig.from_mapping(request.indicator_id, request.bar_type, request.parameters)
        )
