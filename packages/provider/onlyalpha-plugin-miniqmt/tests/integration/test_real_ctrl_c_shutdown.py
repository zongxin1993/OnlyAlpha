"""Opt-in Windows acceptance for real MiniQMT read-only Ctrl+C shutdown."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

import pytest

from onlyalpha.config import OnlyClusterRunConfig

pytestmark = [
    pytest.mark.external,
    pytest.mark.miniqmt,
    pytest.mark.requires_local_qmt,
    pytest.mark.windows,
    pytest.mark.skipif(
        os.environ.get("ONLYALPHA_MINIQMT_CTRL_C") != "1",
        reason="set ONLYALPHA_MINIQMT_CTRL_C=1 for the read-only local shutdown gate",
    ),
]


def test_real_miniqmt_ctrl_break_closes_all_read_only_runtime_resources(tmp_path: Path) -> None:
    baseline = OnlyClusterRunConfig.load("examples/configs/miniqmt_paper_macd.yaml")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    userdata_mini = Path(
        os.environ.get("userdata_mini_path")
        or os.environ.get("ONLYALPHA_MINIQMT_PATH")
        or r"C:\国金证券QMT交易端\userdata_mini"
    )
    payload["data_sources"][0]["extensions"]["userdata_mini_path"] = str(userdata_mini)
    assert not any(item["enabled"] for item in payload["brokers"])
    config = tmp_path / "miniqmt-paper-shutdown.json"
    config.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log_path = tmp_path / "shutdown.log"

    with log_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "onlyalpha.cli",
                "run",
                "--config",
                str(config),
                "--user-data",
                str(tmp_path / "user_data"),
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            deadline = monotonic() + 120
            while monotonic() < deadline:
                output.flush()
                current = log_path.read_text(encoding="utf-8")
                if "OnlyAlpha Engine running" in current:
                    break
                if process.poll() is not None:
                    pytest.fail(f"MiniQMT Paper exited before RUNNING:\n{current}")
                sleep(0.1)
            else:
                pytest.fail("MiniQMT Paper did not reach RUNNING within 120 seconds")

            process.send_signal(signal.CTRL_BREAK_EVENT)
            assert process.wait(timeout=15) == 130
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    log = log_path.read_text(encoding="utf-8")
    assert "Traceback" not in log
    assert "OnlyAlpha shutdown completed" in log
    assert '"status": "STOPPED"' in log
    assert '"runtime_state": "CLOSED"' in log
    assert '"streaming_phase": "STOPPED"' in log
    assert '"subscription_active": false' in log
    assert '"worker_alive": false' in log
    assert '"observation_publisher_alive": false' in log
