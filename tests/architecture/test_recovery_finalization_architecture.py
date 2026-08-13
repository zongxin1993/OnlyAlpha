from pathlib import Path


def test_runtime_delegates_post_recovery_authority_to_finalizer() -> None:
    runtime = Path("src/onlyalpha/runtime/trading_facade.py").read_text(encoding="utf-8")
    assert "def _validate_post_recovery_authority" not in runtime
    assert "_runtime_recovery_finalizer.finalize(outcome)" in runtime
    for code in (
        "POST_RECOVERY_TRANSACTION_SEQUENCE_GAP",
        "POST_RECOVERY_UNPROJECTED_TRANSACTION",
        "POST_RECOVERY_CURSOR_BOUNDARY_MISMATCH",
    ):
        assert code not in runtime


def test_validator_is_read_only_and_runtime_agnostic() -> None:
    validator = Path("src/onlyalpha/runtime/recovery/validation.py").read_text(encoding="utf-8")
    assert "OnlyRuntimeServices" not in validator
    assert "onlyalpha.runtime.backtest.runtime" not in validator
    assert "OnlyVirtualBrokerGateway" not in validator
    for forbidden in ("._records", "._positions", "._orders", "._reservations"):
        assert forbidden not in validator
    for forbidden in (
        ".commit(",
        ".reserve(",
        ".release(",
        "FeeResolver",
        "SettlementRule",
        "MarginFormula",
        "EventGate",
    ):
        assert forbidden not in validator


def test_validation_closure_keeps_the_single_structured_outbox_identity() -> None:
    persistence = Path("src/onlyalpha/transaction/persistence_ports.py").read_text(encoding="utf-8")
    key = persistence[
        persistence.index("class OnlyRuntimeTransactionOutboxKey") : persistence.index(
            "class OnlyRuntimeTransactionOutboxRecord"
        )
    ]
    for field in ("runtime_id", "execution_sequence", "event_sequence"):
        assert field in key
    assert "idempotency_key" not in key


def test_finalizer_distinguishes_inbound_and_event_bus_quiescence_errors() -> None:
    finalizer = Path("src/onlyalpha/runtime/recovery/finalizer.py").read_text(encoding="utf-8")
    assert 'RuntimeError("POST_RECOVERY_SEMANTIC_QUIESCENCE_NOT_PROVEN")' in finalizer
    assert 'RuntimeError("POST_RECOVERY_EVENT_BUS_NOT_DRAINED")' in finalizer
    assert "market_data_inbound_count != 0" not in finalizer


def test_finalizer_orders_verify_before_recovered_transition() -> None:
    finalizer = Path("src/onlyalpha/runtime/recovery/finalizer.py").read_text(encoding="utf-8")
    assert finalizer.index("verify_durable(checkpoint)") < finalizer.index("mark_recovered_all()")
    assert "capture(self._created_at())" in finalizer
    assert "self._checkpoint_service.write(checkpoint)" in finalizer
    assert "publish_pending" not in finalizer
    assert "resume_recovered_all" not in finalizer


def test_cluster_recovery_callback_and_recovered_transition_are_separate() -> None:
    base = Path("src/onlyalpha/cluster/base.py").read_text(encoding="utf-8")
    manager = Path("src/onlyalpha/cluster/manager.py").read_text(encoding="utf-8")
    assert 'RECOVERY_FINALIZING = "RECOVERY_FINALIZING"' in base
    assert "def complete_recovery_all" not in manager
    assert "def fail_recovery_all" not in manager
    begin = manager[
        manager.index("    def begin_recovery_finalization_all") : manager.index("    def mark_recovered_all")
    ]
    assert "on_recovery_complete()" in begin
    assert "OnlyClusterState.RECOVERED" not in begin
    cleanup = manager[manager.index("    def fail_recovery_finalization_all") : manager.index("    def start(")]
    for state in ("RECOVERING", "RECOVERY_FINALIZING", "RECOVERED"):
        assert f"OnlyClusterState.{state}" in cleanup


def test_post_recovery_checkpoint_has_full_read_back_verification() -> None:
    service = Path("src/onlyalpha/runtime/checkpoint/service.py").read_text(encoding="utf-8")
    assert "def capture(" in service
    assert "def write(" in service
    assert "def verify_durable(" in service
    assert "actual.components != expected.components" in service
    assert "aggregate_payload_hash" in service
    assert "latest_checkpoint(self._runtime_id)" in service
