from onlyalpha.indicator.identifiers import ROLLING_VOLATILITY
from onlyalpha.indicator.standard_factory import OnlyStandardIndicatorFactory


class OnlyRollingVolatilityIndicatorFactory(OnlyStandardIndicatorFactory):
    indicator_type = ROLLING_VOLATILITY
    default_period = 20
