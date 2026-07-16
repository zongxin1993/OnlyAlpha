from decimal import Decimal

from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.factory import OnlyIndicatorCreateRequest
from onlyalpha.indicator.identifiers import OnlyIndicatorTypeId
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot
from onlyalpha.indicator.standard import OnlyRollingIndicatorConfig, OnlyStandardBarIndicator


class OnlyStandardIndicatorFactory:
    indicator_type: OnlyIndicatorTypeId
    default_period: int

    def create(self, request: OnlyIndicatorCreateRequest) -> OnlyBarIndicator[OnlyIndicatorSnapshot]:
        period = int(str(request.parameters.get("period", self.default_period)))
        field = str(request.parameters.get("price_field", "CLOSE"))
        deviations = Decimal(str(request.parameters.get("standard_deviations", "2")))
        return OnlyStandardBarIndicator(
            OnlyRollingIndicatorConfig(request.indicator_id, request.bar_type, period, field, deviations),
            self.indicator_type,
        )
