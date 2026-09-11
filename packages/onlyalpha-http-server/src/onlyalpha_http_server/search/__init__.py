"""Search Product HTTP projection."""

from .routes import SEARCH_ROUTE_TAG, create_search_router
from .schema import OnlySearchProductHttpBoundary
from .service import OnlySearchProductHttpServiceV1

__all__ = [
    "OnlySearchProductHttpBoundary",
    "OnlySearchProductHttpServiceV1",
    "SEARCH_ROUTE_TAG",
    "create_search_router",
]
