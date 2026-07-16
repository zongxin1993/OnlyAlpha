from onlyalpha.indicator.identifiers import EMA
from onlyalpha.indicator.standard_factory import OnlyStandardIndicatorFactory


class OnlyEmaIndicatorFactory(OnlyStandardIndicatorFactory):
    indicator_type = EMA
    default_period = 20
