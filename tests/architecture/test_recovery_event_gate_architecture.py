import ast
from pathlib import Path


def _imports(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
    return result


def test_event_bus_remains_runtime_and_recovery_agnostic() -> None:
    source = Path("src/onlyalpha/event/bus.py").read_text(encoding="utf-8")
    imports = _imports("src/onlyalpha/event/bus.py")
    assert not any(name.startswith("onlyalpha.runtime") for name in imports)
    assert "recovery" not in source.lower()
    assert "GatePhase" not in source
    assert "def publish_many_atomic(" in source


def test_business_publishers_do_not_own_event_bus_or_runtime_router() -> None:
    for path in (
        "src/onlyalpha/order/publisher.py",
        "src/onlyalpha/risk/publisher.py",
        "src/onlyalpha/transaction/delivery.py",
    ):
        imports = _imports(path)
        assert "onlyalpha.event.bus" not in imports
        assert "onlyalpha.runtime.events.router" not in imports
        assert "onlyalpha.runtime.events.gate" not in imports


def test_processor_and_commit_coordinator_do_not_depend_on_router_or_gate() -> None:
    for path in (
        "src/onlyalpha/execution/processor.py",
        "src/onlyalpha/transaction/coordinator.py",
    ):
        imports = _imports(path)
        assert "onlyalpha.runtime.events.router" not in imports
        assert "onlyalpha.runtime.events.gate" not in imports


def test_runtime_router_is_the_only_business_event_bus_writer() -> None:
    allowed = {
        Path("src/onlyalpha/event/bus.py"),
        Path("src/onlyalpha/runtime/events/router.py"),
    }
    writers: set[Path] = set()
    for path in Path("src/onlyalpha").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "._event_bus.publish(" in source or "owned_bus.publish(" in source or "owned_bus.publish_many(" in source:
            writers.add(path)
    assert writers <= allowed
    backtest_source = Path("src/onlyalpha/runtime/backtest/runtime.py").read_text(encoding="utf-8")
    runtime_source = Path("src/onlyalpha/runtime/runtime.py").read_text(encoding="utf-8")
    assert "owned_bus.publish(" not in backtest_source
    assert "owned_bus.publish_many(" not in backtest_source
    assert "event_bus.publish(" not in runtime_source


def test_runtime_public_event_bus_is_a_subscription_view() -> None:
    runtime_source = Path("src/onlyalpha/runtime/runtime.py").read_text(encoding="utf-8")
    view_source = Path("src/onlyalpha/event/subscription_view.py").read_text(encoding="utf-8")
    assert "def event_bus(self) -> OnlyEventBusSubscriptionView" in runtime_source
    for forbidden in ("def publish(", "def publish_many(", "def dispatch(", "def drain(", "def close("):
        assert forbidden not in view_source


def test_gate_is_operational_only_and_finalizer_does_not_deliver_outbox() -> None:
    gate_source = Path("src/onlyalpha/runtime/events/gate.py").read_text(encoding="utf-8")
    finalizer_source = Path("src/onlyalpha/runtime/recovery/finalizer.py").read_text(encoding="utf-8")
    runtime_source = Path("src/onlyalpha/runtime/backtest/runtime.py").read_text(encoding="utf-8")
    assert "CheckpointParticipant" not in gate_source
    assert "capture_checkpoint" not in gate_source
    assert "business_projection" not in gate_source
    assert "publish_pending" not in finalizer_source
    assert "execution_outbox_publisher" not in finalizer_source
    assert "execution_outbox_publisher" in runtime_source


def test_hardening_support_remains_test_only_and_adds_no_delivery_authority() -> None:
    assert not any(path.name == "recovery_event_gate_hardening_support.py" for path in Path("src").rglob("*.py"))
    sources = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha").rglob("*.py"))
    for forbidden in (
        "SubscriberAck",
        "DeliveryWatermark",
        "ExactlyOnce",
        "DirectDurableJournal",
    ):
        assert forbidden not in sources


def test_atomic_batch_is_transport_only_and_router_owns_bootstrap_flush() -> None:
    bus_source = Path("src/onlyalpha/event/bus.py").read_text(encoding="utf-8")
    router_source = Path("src/onlyalpha/runtime/events/router.py").read_text(encoding="utf-8")
    assert "publish_many_atomic" in bus_source
    assert "onlyalpha.runtime" not in bus_source
    assert "GatePhase" not in bus_source
    assert "self._event_bus.publish_many_atomic(staged)" in router_source


def test_gate_diagnostics_do_not_enter_result_projection_or_fingerprint() -> None:
    result_sources = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha/result").rglob("*.py"))
    assert "event_gate_snapshot" not in result_sources
    assert "suppressed_direct_count" not in result_sources
