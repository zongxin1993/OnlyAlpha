from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.ledger import OnlyFeeApplicationRecord
from onlyalpha.margin.manager import OnlyMarginRecord
from onlyalpha.margin.models import OnlyMarginReservation
from onlyalpha.runtime.recovery.validation import (
    OnlyFeeSettlementMarginAuthorityCheck,
    OnlyPostRecoveryCheckStatus,
)
from onlyalpha.settlement.identifiers import OnlySettlementInstructionId
from tests.runtime.recovery.support.authority_fixture import OnlyPostRecoveryAuthorityFixture
from tests.runtime.recovery.test_post_recovery_order_reservation_authority import _account, _authorities


def _failed(context) -> set[str]:  # type: ignore[no-untyped-def]
    return {
        item.code
        for item in OnlyFeeSettlementMarginAuthorityCheck().evaluate(context)
        if item.status is OnlyPostRecoveryCheckStatus.FAILED
    }


def test_fee_settlement_authority_passes_for_matching_transaction() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    assert not _failed(fixture.context())


def test_missing_and_total_mismatched_fee_records_remain_detected() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    assert "POST_RECOVERY_FEE_RECORD_MISSING" in _failed(fixture.context(fee_records=()))
    record = fixture.context().fee_records[0]
    changed = replace(
        record,
        incremental_amount=OnlyMoney(
            record.incremental_amount.amount + 1,
            record.incremental_amount.currency,
        ),
    )
    assert "POST_RECOVERY_FEE_TOTAL_MISMATCH" in _failed(
        fixture.context(fee_records=(changed, *fixture.context().fee_records[1:]))
    )


@pytest.mark.parametrize(
    "field,value",
    (
        ("account_id", "wrong-account"),
        ("instrument_id", "wrong-instrument"),
        ("order_id", "wrong-order"),
        ("trade_id", "wrong-trade"),
        ("incremental_amount", OnlyMoney(Decimal("0"), OnlyCurrency("USD"))),
    ),
)
def test_fee_scope_fields_are_compared_to_committed_fact(field: str, value: object) -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    records = fixture.context().fee_records
    changed = replace(records[0], **{field: value})
    assert "POST_RECOVERY_FEE_SCOPE_MISMATCH" in _failed(fixture.context(fee_records=(changed, *records[1:])))


def test_orphan_fee_record_is_rejected() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    record: OnlyFeeApplicationRecord = replace(fixture.context().fee_records[0], application_id="orphan")
    assert "POST_RECOVERY_ORPHAN_FEE_RECORD" in _failed(
        fixture.context(fee_records=(*fixture.context().fee_records, record))
    )


def test_missing_settlement_record_remains_detected() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    assert "POST_RECOVERY_SETTLEMENT_RECORD_MISSING" in _failed(fixture.context(settlement_records=()))


def test_settlement_account_scope_is_compared_to_committed_fact() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    record = fixture.context().settlement_records[0]
    changed = replace(
        record,
        instruction=replace(record.instruction, account_id=type(record.instruction.account_id)("wrong-account")),
    )
    assert "POST_RECOVERY_SETTLEMENT_SCOPE_MISMATCH" in _failed(fixture.context(settlement_records=(changed,)))


def test_orphan_settlement_record_is_rejected() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    original = fixture.context().settlement_records[0]
    record = replace(
        original,
        instruction=replace(
            original.instruction,
            instruction_id=OnlySettlementInstructionId("SINS-" + "0" * 64),
        ),
    )
    assert "POST_RECOVERY_ORPHAN_SETTLEMENT_RECORD" in _failed(
        fixture.context(settlement_records=(*fixture.context().settlement_records, record))
    )


def test_generic_t0_cash_margin_checks_are_not_applicable() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    checks = OnlyFeeSettlementMarginAuthorityCheck().evaluate(fixture.context())
    margin = {item.code: item.status for item in checks if "MARGIN" in item.code}
    assert set(margin.values()) == {OnlyPostRecoveryCheckStatus.NOT_APPLICABLE}


def _margin_context(*, reserved: str = "10", occupied: str = "5", released: str = "2", currency: str = "CNY"):
    fixture, order, _, _, _ = _authorities()
    now = fixture.context().runtime_boundary_view.clock_time
    account = replace(
        _account(fixture, frozen="0"),
        reserved_margin=OnlyMoney(Decimal("10"), OnlyCurrency("CNY")),
        occupied_margin=OnlyMoney(Decimal("5"), OnlyCurrency("CNY")),
        released_margin=OnlyMoney(Decimal("2"), OnlyCurrency("CNY")),
        available_margin=OnlyMoney(Decimal("85"), OnlyCurrency("CNY")),
    )
    reservation = OnlyMarginReservation(
        "margin-reservation",
        fixture.runtime_id,
        order.account_id,
        order.instrument_id,
        order.order_id,
        OnlyCurrency(currency),
        Decimal(reserved) + Decimal(occupied) + Decimal(released),
        Decimal(reserved),
        Decimal(occupied),
        Decimal(released),
        Decimal(0),
        now,
        now,
        1,
    )
    return fixture.context(accounts=(account,), margin_reservations=(reservation,))


def test_margin_reservations_reduce_to_account_margin_authority() -> None:
    assert "POST_RECOVERY_MARGIN_ACCOUNT_MISMATCH" not in _failed(_margin_context())


@pytest.mark.parametrize(
    "values",
    (
        {"reserved": "11"},
        {"occupied": "6"},
        {"released": "3"},
        {"currency": "USD"},
    ),
)
def test_margin_account_amounts_and_currency_must_match(values: dict[str, str]) -> None:
    assert "POST_RECOVERY_MARGIN_ACCOUNT_MISMATCH" in _failed(_margin_context(**values))


def test_negative_margin_record_remains_a_state_failure() -> None:
    context = _margin_context()
    account = context.accounts[0]
    record = OnlyMarginRecord(
        1,
        "RESERVE",
        str(account.account_id),
        "instrument",
        "order",
        "trade",
        account.base_currency.code,
        Decimal("-1"),
        Decimal(0),
        Decimal(0),
        Decimal(0),
    )
    assert "POST_RECOVERY_MARGIN_STATE_MISMATCH" in _failed(replace(context, margin_records=(record,)))
