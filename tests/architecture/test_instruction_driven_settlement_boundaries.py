from pathlib import Path

_SRC = Path(__file__).parents[2] / "src" / "onlyalpha"


def test_removed_settlement_and_execution_transaction_apis_do_not_return() -> None:
    forbidden = (
        "OnlySettlementService",
        "OnlyT1SettlementRule",
        "OnlySettlementManager",
        "OnlyPositionManager.settle",
        "OnlyPositionAllocationManager.settle",
        "OnlyExecutionCommitCoordinator",
        "OnlyPreparedExecutionTransaction",
        "OnlySettlementRuntimeInstruction",
        "settlement_manager.advance",
        "settle_positions",
    )
    production = "\n".join(path.read_text(encoding="utf-8") for path in _SRC.rglob("*.py"))
    assert not {token for token in forbidden if token in production}


def test_runtime_transaction_envelope_has_no_broker_dependency() -> None:
    transaction = (_SRC / "transaction" / "transaction.py").read_text(encoding="utf-8")
    assert "onlyalpha.broker" not in transaction
    assert "broker_update_id" not in transaction
    assert "gateway_id" not in transaction
