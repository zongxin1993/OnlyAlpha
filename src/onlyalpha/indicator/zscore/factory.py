from onlyalpha.indicator.identifiers import ZSCORE
from onlyalpha.indicator.standard_factory import OnlyStandardIndicatorFactory


class OnlyZscoreIndicatorFactory(OnlyStandardIndicatorFactory):
    indicator_type = ZSCORE
    default_period = 20
