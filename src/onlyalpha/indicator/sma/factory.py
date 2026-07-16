from onlyalpha.indicator.identifiers import SMA
from onlyalpha.indicator.standard_factory import OnlyStandardIndicatorFactory


class OnlySmaIndicatorFactory(OnlyStandardIndicatorFactory):
    indicator_type = SMA
    default_period = 20
