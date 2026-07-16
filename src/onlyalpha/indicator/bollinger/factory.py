from onlyalpha.indicator.identifiers import BOLLINGER
from onlyalpha.indicator.standard_factory import OnlyStandardIndicatorFactory


class OnlyBollingerIndicatorFactory(OnlyStandardIndicatorFactory):
    indicator_type = BOLLINGER
    default_period = 20
