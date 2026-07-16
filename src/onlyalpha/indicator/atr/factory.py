from onlyalpha.indicator.identifiers import ATR
from onlyalpha.indicator.standard_factory import OnlyStandardIndicatorFactory


class OnlyAtrIndicatorFactory(OnlyStandardIndicatorFactory):
    indicator_type = ATR
    default_period = 14
