from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from onlyalpha_plugin_binance.common.private_http import (
    OnlyBinanceDispatchKnowledge,
    OnlyBinancePrivateRequestError,
)
from onlyalpha_plugin_binance.spot.broker.codec import only_binance_client_order_id
from onlyalpha_plugin_binance.spot.broker.discovery import OnlyBinanceSpotVenueDiscovery
from onlyalpha_plugin_binance.spot.broker.gateway import OnlyBinanceSpotBrokerGateway

from onlyalpha.broker.enums import OnlyBrokerConnectionState, OnlyBrokerOperationStatus
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerRequestId
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.broker.models import OnlyBrokerOrderRequest
from onlyalpha.broker.reconciliation import (
    OnlyBrokerFactApplicationReceipt,
    OnlyBrokerFactApplicationStatus,
    OnlyBrokerReadinessAuthority,
    OnlyBrokerReconciliationCoordinator,
    OnlyDurableBrokerCommandEvidenceStore,
)
from onlyalpha.broker.updates import OnlyBrokerOrderAcceptedUpdate, OnlyBrokerTradeUpdate
from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.fee.estimate import OnlyOrderFeeEstimate, OnlyOrderFundingPlan
from onlyalpha.fee.models import (
    OnlyBrokerFeeAccountScope,
    OnlyBrokerFeeAccountScopeType,
    OnlyBrokerFeeContractIdentity,
    OnlyFeeAssessment,
    OnlyFeeSubject,
    OnlyLocalFeeFinality,
    OnlyMarketFeePackIdentity,
    OnlyOrderFeeApplicabilityScopeIdentity,
    OnlyOrderFeePolicyBinding,
)
from onlyalpha.order.execution.models import OnlyExecutionSubmissionOutcome
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager


class _AcceptedThenLostRest:
    def __init__(self, *, filled: bool = False) -> None:
        self.orders: dict[str, OnlyBrokerOrderRequest] = {}
        self.submit_count = 0
        self.query_clients: list[str] = []
        self.filled = filled

    def submit_order(self, request: OnlyBrokerOrderRequest) -> bytes:
        self.submit_count += 1
        wire = only_binance_client_order_id(request.client_order_id)
        assert wire not in self.orders
        self.orders[wire] = request
        raise OnlyBinancePrivateRequestError(
            "BINANCE_PRIVATE_REQUEST_UNKNOWN",
            OnlyBinanceDispatchKnowledge.UNKNOWN,
        )

    def query_order(self, *, symbol, client_order_id=None, venue_order_id=None) -> bytes:
        del venue_order_id
        wire = only_binance_client_order_id(client_order_id)
        self.query_clients.append(wire)
        request = self.orders[wire]
        assert symbol == request.instrument_id.symbol.value
        return json.dumps(
            {
                "symbol": symbol,
                "orderId": 9001,
                "clientOrderId": wire,
                "price": str(request.price.value if request.price is not None else Decimal(0)),
                "origQty": str(request.quantity.value),
                "executedQty": str(request.quantity.value if self.filled else Decimal(0)),
                "status": "FILLED" if self.filled else "NEW",
                "updateTime": 1700000000000,
            }
        ).encode()

    def trades(self, *, symbol, venue_order_id=None, from_id=None) -> bytes:
        del from_id
        if not self.filled:
            return b"[]"
        assert str(venue_order_id) == "9001"
        return json.dumps(
            [
                {
                    "symbol": symbol,
                    "id": 7001,
                    "orderId": 9001,
                    "price": "25000.10",
                    "qty": "0.01000000",
                    "commission": "0.00001000",
                    "commissionAsset": "BTC",
                    "time": 1700000000000,
                    "isMaker": False,
                }
            ]
        ).encode()


def _manager() -> OnlyOrderManager:
    runtime_id = OnlyRuntimeId("runtime")
    return OnlyOrderManager(
        OnlyEngineId("engine"),
        runtime_id,
        OnlySequenceOrderIdGenerator(runtime_id),
        OnlySequenceClientOrderIdGenerator(runtime_id),
    )


def _zero_fee_contract(order, timestamp):
    currency = OnlyCurrency("USDT", 8)
    digest = "0" * 64
    account_scope = OnlyBrokerFeeAccountScope(OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT, order.account_id)
    binding = OnlyOrderFeePolicyBinding.create(
        runtime_id=order.runtime_id,
        account_id=order.account_id,
        cluster_id=order.cluster_id,
        order_id=order.order_id,
        instrument_id=order.instrument_id,
        market_product_id="TEST_BINANCE_SPOT",
        market_product_version="1",
        market_fee_pack=OnlyMarketFeePackIdentity("TEST_MARKET_FEES", "1", digest),
        broker_fee_contract=OnlyBrokerFeeContractIdentity(
            "TEST_BROKER_FEES",
            "1",
            "BINANCE",
            account_scope,
            digest,
        ),
        applicability_scope=OnlyOrderFeeApplicabilityScopeIdentity.create(
            market_product_id="TEST_BINANCE_SPOT",
            market="CRYPTO",
            venue="BINANCE",
            instrument_class="SPOT",
            broker_id="BINANCE",
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            charge_currency=currency,
        ),
        order_fixed_schedules=(),
        fill_effective_families=(),
        charge_currency=currency,
        bound_at=timestamp,
    )
    zero = OnlyMoney(Decimal(0), currency)
    subject = OnlyFeeSubject(
        order.runtime_id,
        order.account_id,
        order.cluster_id,
        order.order_id,
        order.instrument_id,
    )
    assessment = OnlyFeeAssessment(
        "test-zero-fee",
        subject,
        None,
        (),
        zero,
        zero,
        digest,
        digest,
        OnlyLocalFeeFinality.MODEL_CONFIRMED,
        binding,
    )
    estimate = OnlyOrderFeeEstimate(assessment, assessment, zero, zero, digest)
    principal = OnlyMoney((order.price.value * order.quantity.value).quantize(Decimal("0.00000001")), currency)
    funding = OnlyOrderFundingPlan(order.order_id, principal, zero, principal, digest, digest)
    return binding, estimate, funding


@pytest.mark.parametrize("symbol", ("BTCUSDT", "ETHUSDT"))
def test_unknown_dispatch_crash_recovers_same_external_order_and_identity(
    tmp_path: Path,
    symbol: str,
) -> None:
    manager = _manager()
    created = manager.create_order(
        OnlyOrderRequest(
            OnlyOrderRequestId(f"request-{symbol}"),
            OnlyInstrumentId.parse(f"{symbol}.BINANCE"),
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("0.01000000"), 8),
            price=OnlyPrice(Decimal("25000.10"), 2),
        ),
        OnlyClusterId("cluster"),
        OnlyAccountId("spot-testnet"),
        OnlyTimestamp.from_unix_nanos(1),
        _zero_fee_contract,
    )
    assert manager.mark_submitted(created.order_id, OnlyTimestamp.from_unix_nanos(2)).changed
    order = manager.require_snapshot(created.order_id)
    request = OnlyBrokerOrderRequest(
        OnlyBrokerRequestId(f"submit-{symbol}"),
        order.order_id,
        order.client_order_id,
        order.account_id,
        order.instrument_id,
        order.side,
        order.offset,
        order.order_type,
        order.time_in_force,
        order.quantity,
        order.price,
        order.submitted_at or order.created_at,
    )
    rest = _AcceptedThenLostRest(filled=symbol == "BTCUSDT")
    evidence_path = (tmp_path / symbol / "commands.jsonl").resolve()
    readiness = OnlyBrokerReadinessAuthority()
    readiness.transport_connected()
    readiness.authenticated()
    readiness.account_scope_established()
    readiness.discovery_completed()
    readiness.reconciliation_converged()
    readiness.stream_trusted()
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=order.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore(evidence_path),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(3),
    )
    result = gateway.submit_order(request)
    assert result.status is OnlyBrokerOperationStatus.UNKNOWN
    manager.record_submission_outcome(order.order_id, OnlyExecutionSubmissionOutcome.UNKNOWN)
    checkpoint = manager.capture_checkpoint()

    recovered_manager = _manager()
    recovered_manager.restore_checkpoint(checkpoint)
    recovered_order = recovered_manager.require_snapshot(order.order_id)
    recovered_readiness = OnlyBrokerReadinessAuthority()
    recovered_gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=order.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=recovered_readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore(evidence_path),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(1_700_000_001_000_000_000),
    )
    recovered_gateway.restore_order_request(request)
    recovered_readiness.transport_connected()
    recovered_readiness.authenticated()
    recovered_readiness.account_scope_established()
    recovered_readiness.discovery_completed()
    assert recovered_gateway.submit_order(request).status is OnlyBrokerOperationStatus.UNKNOWN

    inbound = OnlyBoundedBrokerInboundQueue(8)
    coordinator = OnlyBrokerReconciliationCoordinator(
        OnlyBinanceSpotVenueDiscovery(
            runtime_id=recovered_order.runtime_id,
            gateway_id=OnlyBrokerGatewayId("binance-testnet"),
            account_id=recovered_order.account_id,
            rest=rest,  # type: ignore[arg-type]
            gateway=recovered_gateway,
            now=lambda: OnlyTimestamp.from_unix_nanos(1_700_000_001_000_000_000),
        ),
        inbound,
        recovered_readiness,
        OnlyDurableBrokerCommandEvidenceStore(evidence_path),
        lambda: OnlyTimestamp.from_unix_nanos(1_700_000_002_000_000_000),
    )
    recovered_manager.begin_submission_reconciliation(order.order_id)
    updates = coordinator.reconcile_unknown(recovered_order)
    assert updates == inbound.drain()
    accepted_updates = tuple(item for item in updates if isinstance(item, OnlyBrokerOrderAcceptedUpdate))
    receipts = []
    for accepted in accepted_updates:
        accepted_result = recovered_manager.apply_accepted(
            accepted.order_id,
            accepted.ts_init,
            accepted.venue_order_id,
            external_sequence=accepted.source_sequence,
            external_event_id=str(accepted.update_id),
            event_time=accepted.ts_event,
        )
        assert accepted_result.changed
        receipts.append(OnlyBrokerFactApplicationReceipt(accepted.update_id, OnlyBrokerFactApplicationStatus.APPLIED))
    for trade in (item for item in updates if isinstance(item, OnlyBrokerTradeUpdate)):
        trade_result = recovered_manager.apply_fill(trade.fill)
        assert trade_result.changed
        duplicate = recovered_manager.apply_fill(trade.fill)
        assert not duplicate.changed and duplicate.apply_result.value == "DUPLICATE"
        receipts.append(OnlyBrokerFactApplicationReceipt(trade.update_id, OnlyBrokerFactApplicationStatus.APPLIED))
    coordinator.acknowledge_unknown(
        recovered_manager.require_snapshot(order.order_id),
        tuple(receipts),
    )
    recovered_readiness.reconciliation_converged()
    recovered_readiness.stream_trusted()

    converged = recovered_manager.require_snapshot(order.order_id)
    assert recovered_manager.submission_outcome(order.order_id) is OnlyExecutionSubmissionOutcome.RESOLVED
    assert converged.client_order_id == order.client_order_id
    assert str(converged.venue_order_id) == "9001"
    assert converged.status is (OnlyOrderStatus.FILLED if symbol == "BTCUSDT" else OnlyOrderStatus.ACCEPTED)
    assert bool(accepted_updates) is (symbol == "ETHUSDT")
    assert rest.submit_count == 1
    assert rest.query_clients and set(rest.query_clients) == {only_binance_client_order_id(order.client_order_id)}
    assert recovered_gateway.connection_snapshot().state is OnlyBrokerConnectionState.READY
