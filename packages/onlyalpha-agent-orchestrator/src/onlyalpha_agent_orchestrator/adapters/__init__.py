"""Narrow external protocol adapters; no generic Agent tool/plugin surface."""

from .openai_compatible import OnlyOpenAICompatibleModelAdapterV1
from .product_api import OnlyContractDrivenProductApiAdapterV1, OnlyProductApiContractV2
from .transport import (
    OnlyHttpDispatchClassification,
    OnlyHttpRequestV1,
    OnlyHttpResponseV1,
    OnlyHttpTransportOutcomeV1,
    OnlyRawHttpTransportV1,
)

__all__ = [
    "OnlyContractDrivenProductApiAdapterV1",
    "OnlyHttpDispatchClassification",
    "OnlyHttpRequestV1",
    "OnlyHttpResponseV1",
    "OnlyHttpTransportOutcomeV1",
    "OnlyOpenAICompatibleModelAdapterV1",
    "OnlyProductApiContractV2",
    "OnlyRawHttpTransportV1",
]
