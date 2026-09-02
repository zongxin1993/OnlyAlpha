from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path


def _module():  # type: ignore[no-untyped-def]
    root = Path(__file__).parents[2]
    for relative in (
        "plugs/onlyalpha-plugin-binance/src",
        "plugs/onlyalpha-plugin-binance-spot/src",
        "plugs/onlyalpha-plugin-binance-usdm/src",
    ):
        sys.path.insert(0, str(root / relative))
    path = root / "deploy/compose/provision_a0_binance_golden.py"
    spec = importlib.util.spec_from_file_location("onlyalpha_binance_golden_provisioner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dataset_event_range_contains_final_closed_bar_event() -> None:
    module = _module()
    start = datetime(2026, 9, 2, 11, 48, tzinfo=UTC)
    end = datetime(2026, 9, 2, 11, 49, tzinfo=UTC)

    event_range = module._dataset_event_range(start, end)

    assert event_range.contains(end)
    assert not event_range.contains(event_range.end)


def test_physical_capture_sessions_are_unique_and_retain_authority() -> None:
    module = _module()

    first = module._capture_session_id("capture-sha256", "segment-1")
    second = module._capture_session_id("capture-sha256", "segment-2")

    assert first == "capture-sha256:segment-1"
    assert second == "capture-sha256:segment-2"
    assert first != second


def test_provisioner_initializes_product_output_roots(tmp_path: Path) -> None:
    module = _module()
    layout = module.OnlyUserDataLayout(tmp_path)

    module._ensure_product_roots(layout)

    assert layout.research_artifact_root.is_dir()
    assert layout.backtest_evidence_root.is_dir()
