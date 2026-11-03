from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def outputs() -> list[dict[str, object]]:
    rows = [json.loads(line) for line in (ROOT / "test-data/order/lifecycle-v1.jsonl").read_text().splitlines()]
    return [{"case": row["case"], "observed": row["expected"]} for row in rows]


def test_native_order_literal_comparison_does_not_load_legacy_backend() -> None:
    code = """
import builtins,json,runpy,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
    assert name!='onlyalpha' and not name.startswith('onlyalpha.'),name
    return original(name,*args,**kwargs)
builtins.__import__=guarded
module=runpy.run_path(sys.argv[1])
module['compare_native_outputs'](json.load(sys.stdin))
"""
    result = subprocess.run(
        [sys.executable, "-B", "-I", "-c", code, str(ROOT / "scripts/order_reference_check.py")],
        input=json.dumps(outputs()),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_order_literals_refuse_missing_reordered_or_changed_output() -> None:
    from scripts.order_reference_check import compare_native_outputs

    good = outputs()
    wrong = outputs()
    wrong[0]["observed"] = [["FILLED", "4", "99.99", "399.96"]]
    for bad in (good[:-1], list(reversed(good)), wrong):
        with pytest.raises(AssertionError):
            compare_native_outputs(bad)


def test_native_order_fixture_resources_are_isolated_and_selected(tmp_path: Path) -> None:
    import tomllib

    from scripts.rust_kernel_check import affected_packages, isolated_order, validate_order_sources

    manifest = isolated_order(ROOT, tmp_path / "source")
    members = tomllib.loads(manifest.read_text())["workspace"]["members"]
    assert set(members) == {"crates/onlyalpha-kernel/domain", "crates/onlyalpha-kernel/order"}
    assert not (manifest.parent / "crates/onlyalpha-kernel/execution").exists()
    for path in (
        "test-data/order/domain-inputs.json",
        "test-data/execution/domain-inputs.json",
        "test-data/broker/domain-inputs.json",
        "test-data/margin/common-v1.json",
        "test-data/position/valuation-order-contract.json",
    ):
        assert (manifest.parent / path).read_bytes() == (ROOT / path).read_bytes()
        assert "onlyalpha-order" in affected_packages(ROOT, (path,))
    validate_order_sources(ROOT)
