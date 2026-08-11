"""Public surface of the CN A-share Market Product plugin."""

from onlyalpha_market_cn_ashare.config import OnlyCnAshareConfig as OnlyCnAshareConfig
from onlyalpha_market_cn_ashare.factory import (
    OnlyCnAshareMarketProductFactory as OnlyCnAshareMarketProductFactory,
)
from onlyalpha_market_cn_ashare.reference import (
    OnlyCnAshareBoard as OnlyCnAshareBoard,
)
from onlyalpha_market_cn_ashare.reference import (
    OnlyCnAshareExchange as OnlyCnAshareExchange,
)
from onlyalpha_market_cn_ashare.reference import (
    OnlyCnAshareInstrumentReference as OnlyCnAshareInstrumentReference,
)
from onlyalpha_market_cn_ashare.reference import (
    OnlyCnAshareReferenceAuthority as OnlyCnAshareReferenceAuthority,
)
from onlyalpha_market_cn_ashare.reference import (
    OnlyCnAshareReferenceError as OnlyCnAshareReferenceError,
)
from onlyalpha_market_cn_ashare.reference import (
    OnlyCnAshareReferenceSource as OnlyCnAshareReferenceSource,
)
from onlyalpha_market_cn_ashare.reference import (
    OnlyCnAshareSecurityType as OnlyCnAshareSecurityType,
)

__all__ = [name for name in globals() if name.startswith("Only")]
