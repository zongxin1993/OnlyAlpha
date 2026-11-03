"""Frozen normalized facts remain usable without the retired Python broker producer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_frozen_broker_corpus_does_not_import_legacy_backend() -> None:
    code = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    assert name != "onlyalpha" and not name.startswith(("onlyalpha.", "onlyalpha_plugin_broker_virtual")), name
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from scripts.broker_reference_check import virtual_corpus
assert len(virtual_corpus()) == 9
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


def test_frozen_broker_corpus_refuses_drift(tmp_path: Path) -> None:
    from scripts.broker_reference_check import ROOT, virtual_corpus

    path = tmp_path / "test-data/broker/virtual-v2.json"
    path.parent.mkdir(parents=True)
    raw = (ROOT / "test-data/broker/virtual-v2.json").read_bytes()
    path.write_bytes(raw.replace(b'"40"', b'"41"'))
    with pytest.raises(ValueError, match="BROKER_VIRTUAL_FIXTURE_DRIFT"):
        virtual_corpus(tmp_path)
