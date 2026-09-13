from pathlib import Path

from tests.architecture._architecture_imports import syntactic_imported_modules_for_path


def test_event_buffer_is_a_pure_event_production_component() -> None:
    imports = syntactic_imported_modules_for_path("src/onlyalpha/execution/event_buffer.py")
    assert "onlyalpha.event.bus" not in imports
    assert not any(name.endswith("execution.journal") for name in imports)
    source = Path("src/onlyalpha/execution/event_buffer.py").read_text(encoding="utf-8")
    for removed in ("publish", "publish_many", "snapshot", "drain", "discard", "commit", "rollback"):
        assert f"def {removed}(" not in source


def test_processor_knows_commit_but_not_delivery_implementations_or_event_bus() -> None:
    imports = syntactic_imported_modules_for_path("src/onlyalpha/execution/processor.py")
    assert "onlyalpha.event.bus" not in imports
    source = Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8")
    assert "OnlyDirectExecutionEventPublisher" not in source
    assert "OnlyExecutionOutboxPublisher" not in source
    assert ".publish_pending(" not in source


def test_plugins_do_not_own_execution_delivery_or_journal() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (Path("packages/fake"), Path("packages/provider"))
        for path in root.rglob("*.py")
    )
    assert "OnlyExecutionEventDeliveryCoordinator" not in source
    assert "OnlyExecutionCommitPort" not in source
    assert "OnlyExecutionOutboxPort" not in source
