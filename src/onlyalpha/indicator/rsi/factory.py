from onlyalpha.indicator.identifiers import RSI
from onlyalpha.indicator.standard_factory import OnlyStandardIndicatorFactory


class OnlyRsiIndicatorFactory(OnlyStandardIndicatorFactory):
    indicator_type = RSI
    default_period = 14
