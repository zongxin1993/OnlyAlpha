"""Public Core contract for Trading Market Product plugins."""

from onlyalpha.market.product.binding import OnlyResolvedMarketProductBinding as OnlyResolvedMarketProductBinding
from onlyalpha.market.product.config import (
    OnlyCanonicalMarketProductConfig as OnlyCanonicalMarketProductConfig,
)
from onlyalpha.market.product.config import (
    OnlyMarketProductConfig as OnlyMarketProductConfig,
)
from onlyalpha.market.product.config import (
    OnlyMarketProductConfigScalar as OnlyMarketProductConfigScalar,
)
from onlyalpha.market.product.config import (
    OnlyMarketProductConfigValue as OnlyMarketProductConfigValue,
)
from onlyalpha.market.product.contracts import (
    OnlyMarketProductFactory as OnlyMarketProductFactory,
)
from onlyalpha.market.product.contracts import (
    OnlyMarketProductResolutionContext as OnlyMarketProductResolutionContext,
)
from onlyalpha.market.product.contracts import (
    OnlyMarketProductResourceResolver as OnlyMarketProductResourceResolver,
)
from onlyalpha.market.product.errors import (
    OnlyDuplicateMarketProductPluginError as OnlyDuplicateMarketProductPluginError,
)
from onlyalpha.market.product.errors import (
    OnlyInvalidMarketProductConfigurationError as OnlyInvalidMarketProductConfigurationError,
)
from onlyalpha.market.product.errors import (
    OnlyMarketProductAuthorityConflictError as OnlyMarketProductAuthorityConflictError,
)
from onlyalpha.market.product.errors import (
    OnlyMarketProductError as OnlyMarketProductError,
)
from onlyalpha.market.product.errors import (
    OnlyMarketProductResolutionError as OnlyMarketProductResolutionError,
)
from onlyalpha.market.product.errors import (
    OnlyUnknownMarketProductPluginError as OnlyUnknownMarketProductPluginError,
)
from onlyalpha.market.product.errors import (
    OnlyUnsupportedMarketProductError as OnlyUnsupportedMarketProductError,
)
from onlyalpha.market.product.errors import (
    OnlyUnsupportedMarketProductVersionError as OnlyUnsupportedMarketProductVersionError,
)
from onlyalpha.market.product.identity import (
    OnlyMarketProductAuthorityIdentity as OnlyMarketProductAuthorityIdentity,
)
from onlyalpha.market.product.identity import (
    OnlyMarketProductCompositionIdentity as OnlyMarketProductCompositionIdentity,
)
from onlyalpha.market.product.identity import (
    OnlyMarketProductId as OnlyMarketProductId,
)
from onlyalpha.market.product.identity import (
    OnlyMarketProductIdentity as OnlyMarketProductIdentity,
)
from onlyalpha.market.product.identity import (
    OnlyMarketProductPluginId as OnlyMarketProductPluginId,
)
from onlyalpha.market.product.identity import (
    OnlyMarketProductVersion as OnlyMarketProductVersion,
)
from onlyalpha.market.product.ports import (
    OnlyCompiledInstrumentMarketTerms as OnlyCompiledInstrumentMarketTerms,
)
from onlyalpha.market.product.ports import (
    OnlyCompiledMarketPolicy as OnlyCompiledMarketPolicy,
)
from onlyalpha.market.product.ports import (
    OnlyCompiledMarketPolicyIdentity as OnlyCompiledMarketPolicyIdentity,
)
from onlyalpha.market.product.ports import (
    OnlyInstrumentTradingStatus as OnlyInstrumentTradingStatus,
)
from onlyalpha.market.product.ports import (
    OnlyMarketPolicyCompilationRequest as OnlyMarketPolicyCompilationRequest,
)
from onlyalpha.market.product.ports import (
    OnlyMarketPolicyCompiler as OnlyMarketPolicyCompiler,
)
from onlyalpha.market.product.ports import (
    OnlyMarketPolicyReference as OnlyMarketPolicyReference,
)
from onlyalpha.market.product.ports import (
    OnlyMarketReferenceAuthority as OnlyMarketReferenceAuthority,
)
from onlyalpha.market.product.registry import OnlyMarketProductFactoryRegistry as OnlyMarketProductFactoryRegistry

__all__ = [name for name in globals() if name.startswith("Only")]
