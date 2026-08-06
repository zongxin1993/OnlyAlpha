from onlyalpha.execution import (
    OnlyRuntimeProjectionComponent,
    only_decode_prepared_execution_transaction,
    only_encode_prepared_execution_transaction,
)
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def test_long_close_prepared_transaction_has_fixed_projection_order_and_fact_authority() -> None:
    _, context, prepared = only_test_generic_t0_long_close_context(open_quantity="200", close_quantity="100")

    assert tuple(item.identity.component for item in prepared.projections) == (
        OnlyRuntimeProjectionComponent.ORDER,
        OnlyRuntimeProjectionComponent.POSITION,
        OnlyRuntimeProjectionComponent.ALLOCATION,
        OnlyRuntimeProjectionComponent.SETTLEMENT,
        OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL,
        OnlyRuntimeProjectionComponent.FEE_LEDGER,
        OnlyRuntimeProjectionComponent.ACCOUNT,
        OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
        OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK,
        OnlyRuntimeProjectionComponent.VALUATION,
    )
    assert prepared.fact_draft.position_quantity_before == 200
    assert prepared.fact_draft.position_quantity_after == 100
    assert prepared.fact_draft.released_open_price_quantity == 1000
    assert prepared.fact_draft.fill_identity == context.fill_authority.identity
    assert all(item.identity.payload_hash for item in prepared.projections)
    assert prepared.authority_hash and prepared.payload_hash


def test_long_close_prepared_transaction_codec_is_deterministic() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    encoded = only_encode_prepared_execution_transaction(prepared)

    assert only_decode_prepared_execution_transaction(encoded) == prepared
    assert only_encode_prepared_execution_transaction(prepared) == encoded
