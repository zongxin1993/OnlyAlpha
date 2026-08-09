from pathlib import Path


def test_fee_reconciliation_deleted_legacy_boundaries_do_not_return() -> None:
    root = Path("src/onlyalpha")
    risk_gate = (root / "fee/risk_gate.py").read_text()
    runtime = (root / "runtime/backtest/runtime.py").read_text()
    evidence = (root / "fee/evidence.py").read_text()
    planner = (root / "fee/reconciliation.py").read_text()
    assert "OnlyOrderSide" not in risk_gate and "OnlyOffset" not in risk_gate
    assert "reconcile_external_fee" not in runtime
    assert "materiality_threshold" not in runtime
    assert "statement_scope: str" not in evidence
    assert "onlyalpha.runtime" not in planner and "onlyalpha_plugin" not in planner
