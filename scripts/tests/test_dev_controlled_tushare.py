from __future__ import annotations

import pytest

from scripts import dev_verification as verification

pytestmark = pytest.mark.architecture

OPERATION = "162a851b-7dd1-47dd-9156-ff64842ed779"
COMMAND = [
    "python",
    "-m",
    "scripts.native_web_e2e",
    "--controlled-source-https",
    "--retained-market-input",
    "--tushare-daily-market-input",
]


def test_daily_controlled_hosts_are_exact_and_preserve_existing_modes():
    original = b"127.0.0.1 localhost\n"
    mapped = verification.controlled_hosts_bytes(original, OPERATION, tushare_daily=True)
    assert mapped == original + (
        b"127.0.0.1 data-api.binance.vision api.tushare.pro # onlyalpha-dev-controlled-https:"
        + OPERATION.encode()
        + b"\n"
    )
    assert verification.controlled_https_mapping(mapped, OPERATION, tushare_daily=True)
    assert not verification.controlled_https_mapping(mapped, OPERATION)
    assert not verification.controlled_https_mapping(mapped, OPERATION, chart_stream=True)
    assert verification.controlled_hostnames(False) == (b"data-api.binance.vision",)
    assert verification.controlled_hostnames(True) == (b"data-api.binance.vision", b"data-stream.binance.vision")
    assert verification.controlled_https_command(COMMAND)


@pytest.mark.parametrize(
    "original",
    [
        b"127.0.0.1 API.TUSHARE.PRO\n",
        b"127.0.0.1 data-api.binance.vision\n",
        b"# onlyalpha-dev-controlled-https:foreign\n",
    ],
)
def test_daily_rejects_preexisting_controlled_mapping(original):
    with pytest.raises(ValueError, match="EXISTING_MAPPING_REFUSED"):
        verification.controlled_hosts_bytes(original, OPERATION, tushare_daily=True)


@pytest.mark.parametrize(
    "suffix",
    [
        b"127.0.0.2 api.tushare.pro\n",
        b"127.0.0.1 api.tushare.pro\n",
    ],
)
def test_daily_rejects_extra_alias_or_wrong_operation(suffix):
    mapped = verification.controlled_hosts_bytes(b"127.0.0.1 localhost\n", OPERATION, tushare_daily=True)
    assert not verification.controlled_https_mapping(mapped + suffix, OPERATION, tushare_daily=True)
    assert not verification.controlled_https_mapping(mapped, "foreign", tushare_daily=True)


def test_daily_and_stream_modes_cannot_be_combined():
    with pytest.raises(ValueError, match="COMMAND_REFUSED"):
        verification.controlled_hostnames(True, tushare_daily=True)
    assert not verification.controlled_https_command(COMMAND + ["--chart-sma-market-input"])
    assert not verification.controlled_https_command(COMMAND + ["--backtest-market-input"])
    assert not verification.controlled_https_command(COMMAND + ["--tushare-daily-market-input"])
    assert not verification.controlled_https_command([x for x in COMMAND if x != "--retained-market-input"])
    assert not verification.controlled_https_command(["python", "elsewhere.py", *COMMAND[3:]])


def test_backtest_owner_controlled_https_admits_only_the_approved_nodes(monkeypatch):
    path = "packages/backend/tests/application/test_strategy_research_evidence.py"
    node = f"{path}::test_actual_strategy_science_producer_report_historical_reader_and_freeze"
    prefix = ["python", "-m", "pytest", "-q", "-s"]
    expected = [
        [*prefix, f"{node}[backtest-owner:{scenario}]"]
        for scenario in (
            "human-owner-isolation",
            "queued-cancel",
            "running-cancel",
            "shutdown-resume",
            "attempts-exhausted",
            "expiry-before-finalization",
            "expiry-before-recovery-publication",
            "lost-guard",
            "crash-recover",
            "worker-exit",
            "worker-exit-before-claim",
            "worker-exit-during-execution",
            "worker-exit-after-candidate",
            "worker-exit-during-insert",
            "recover-cancel",
            "missing-program",
            "missing-market-seal",
            "missing-market-row",
            "sim-start-refusals",
        )
    ]
    assert {tuple(command) for command in verification.CONTROLLED_BACKTEST_OWNER_FIXTURE_COMMANDS} == {
        tuple(command) for command in expected
    }
    monkeypatch.setattr(verification.os, "geteuid", lambda: 10001)
    for command in expected:
        assert verification.controlled_https_command(command)
        for alternative in (
            [*command, "--collect-only"],
            [*command[:3], "-s", "-q", command[-1]],
            [*command[:-2], command[-1]],
            [*prefix, path],
            [*prefix, node],
            [*prefix, f"{node}[backtest-owner:memory-completion]", "--collect-only"],
            [*prefix, f"{node}[backtest-owner:recover-published]"],
            [*command, f"{node}[backtest-owner:lost-guard]"],
        ):
            assert not verification.controlled_https_command(alternative)
            with pytest.raises(ValueError, match="DEV_CONTROLLED_HTTPS_COMMAND_REFUSED"):
                verification.run_host(
                    "run", alternative, web=False, rebuild=False, reservation={}, controlled_source_https=True
                )
            with pytest.raises(ValueError, match="DEV_CONTROLLED_HTTPS_COMMAND_REFUSED"):
                verification.run_inside(alternative, controlled_source_https=True)


@pytest.mark.parametrize("mode", ["prepare", "run", "inside", "runtime-build"])
def test_internal_daily_flag_is_rejected_outside_root_lifecycle(monkeypatch, mode):
    monkeypatch.setattr(verification.sys, "argv", ["dev_verification.py", "--controlled-tushare-daily", mode])
    with pytest.raises(ValueError, match="COMMAND_REFUSED"):
        verification.main()
