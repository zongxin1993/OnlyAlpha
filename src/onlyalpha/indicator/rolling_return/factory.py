from onlyalpha.indicator.identifiers import ROLLING_RETURN
from onlyalpha.indicator.standard_factory import OnlyStandardIndicatorFactory


class OnlyRollingReturnIndicatorFactory(OnlyStandardIndicatorFactory):
    indicator_type = ROLLING_RETURN
    default_period = 20
