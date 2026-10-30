"""Provider-neutral remote Gateway protocol foundation."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import (
        OnlyGatewayApplicationError as OnlyGatewayApplicationError,
    )
    from .client import (
        OnlyGatewayClient as OnlyGatewayClient,
    )
    from .client import (
        OnlyGatewayConnectionState as OnlyGatewayConnectionState,
    )
    from .client import (
        OnlyGatewayHandshake as OnlyGatewayHandshake,
    )
    from .client import (
        OnlyGatewayProtocolError as OnlyGatewayProtocolError,
    )
    from .client import (
        OnlyGatewayResyncRequired as OnlyGatewayResyncRequired,
    )
    from .client import (
        OnlyGatewayTransportError as OnlyGatewayTransportError,
    )
    from .client import (
        OnlyTestMutationOutcome as OnlyTestMutationOutcome,
    )
    from .client import (
        OnlyTestStreamBatch as OnlyTestStreamBatch,
    )
    from .client import (
        OnlyTestStreamEvent as OnlyTestStreamEvent,
    )
    from .constants import PROTOCOL_MAJOR as PROTOCOL_MAJOR
    from .identity import canonical_test_mutation_fingerprint as canonical_test_mutation_fingerprint

__all__ = [
    "PROTOCOL_MAJOR",
    "OnlyGatewayApplicationError",
    "OnlyGatewayClient",
    "OnlyGatewayConnectionState",
    "OnlyGatewayHandshake",
    "OnlyGatewayProtocolError",
    "OnlyGatewayResyncRequired",
    "OnlyGatewayTransportError",
    "OnlyTestMutationOutcome",
    "OnlyTestStreamBatch",
    "OnlyTestStreamEvent",
    "canonical_test_mutation_fingerprint",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    module = {"PROTOCOL_MAJOR": ".constants", "canonical_test_mutation_fingerprint": ".identity"}.get(name, ".client")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value
