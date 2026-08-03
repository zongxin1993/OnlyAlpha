"""Cluster-scoped ctx.orders capability."""

from collections.abc import Callable

from onlyalpha.domain.execution import OnlyCancelOrderRequest, OnlyOrderRequest, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderId, OnlyOrderRequestId
from onlyalpha.order.exceptions import OnlyOrderScopeError
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.order.results import OnlyOrderCancelResult, OnlyOrderSubmitResult
from onlyalpha.order.service import OnlyOrderService


class OnlyOrderServiceView:
    """Allows submit/cancel and Cluster-local Snapshot queries only."""

    __slots__ = (
        "__account_id",
        "__begin_events",
        "__cluster_id",
        "__complete_events",
        "__enabled",
        "__query",
        "__service",
        "__submit_interceptor",
    )

    def __init__(
        self,
        cluster_id: OnlyClusterId,
        default_account_id: OnlyAccountId,
        service: OnlyOrderService,
        query: OnlyOrderQueryService,
        enabled: Callable[[], bool],
        begin_events: Callable[[], None],
        complete_events: Callable[[bool], None],
        submit_interceptor: Callable[[OnlyOrderRequest], OnlyOrderSubmitResult | None] | None = None,
    ) -> None:
        self.__cluster_id = cluster_id
        self.__account_id = default_account_id
        self.__service = service
        self.__query = query
        self.__enabled = enabled
        self.__begin_events = begin_events
        self.__complete_events = complete_events
        self.__submit_interceptor = submit_interceptor

    def submit(self, request: OnlyOrderRequest) -> OnlyOrderSubmitResult:
        self.__require_enabled()
        if self.__submit_interceptor is not None:
            intercepted = self.__submit_interceptor(request)
            if intercepted is not None:
                return intercepted
        self.__begin_events()
        try:
            result = self.__service.submit(request, self.__cluster_id, self.__account_id)
        except Exception:
            self.__complete_events(False)
            raise
        self.__complete_events(True)
        return result

    def cancel(
        self,
        request: OnlyCancelOrderRequest | OnlyOrderId,
        *,
        request_id: OnlyOrderRequestId | None = None,
        reason: str = "",
    ) -> OnlyOrderCancelResult:
        self.__require_enabled()
        normalized = (
            request
            if isinstance(request, OnlyCancelOrderRequest)
            else OnlyCancelOrderRequest(
                request_id or OnlyOrderRequestId(f"cancel-{request}"),
                request,
                reason,
            )
        )
        self.__require_owned(normalized.order_id)
        self.__begin_events()
        try:
            result = self.__service.cancel(normalized, self.__cluster_id)
        except Exception:
            self.__complete_events(False)
            raise
        self.__complete_events(True)
        return result

    def get(self, order_id: OnlyOrderId) -> OnlyOrderSnapshot | None:
        snapshot = self.__query.get(order_id)
        return snapshot if snapshot is None or snapshot.cluster_id == self.__cluster_id else None

    def require(self, order_id: OnlyOrderId) -> OnlyOrderSnapshot:
        snapshot = self.__query.require(order_id)
        if snapshot.cluster_id != self.__cluster_id:
            raise OnlyOrderScopeError("Cluster cannot query another Cluster's Order")
        return snapshot

    def list_open(self) -> tuple[OnlyOrderSnapshot, ...]:
        return tuple(
            item
            for item in self.__query.list_by_cluster(self.__cluster_id)
            if item.status.value in {"CREATED", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "PENDING_CANCEL"}
        )

    def list_recent(self, limit: int = 100) -> tuple[OnlyOrderSnapshot, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return tuple(reversed(self.__query.list_by_cluster(self.__cluster_id)[-limit:]))

    def __require_owned(self, order_id: OnlyOrderId) -> None:
        snapshot = self.__query.get(order_id)
        if snapshot is None or snapshot.cluster_id != self.__cluster_id:
            raise OnlyOrderScopeError("Cluster cannot cancel another Cluster's Order")

    def __require_enabled(self) -> None:
        if not self.__enabled():
            raise OnlyOrderScopeError("Order commands require a running Cluster and Runtime")


OnlyOrderQueryView = OnlyOrderServiceView
OnlyOrderContextView = OnlyOrderServiceView
