"""精确受控 Backtest 场景入口；不扩大 root 映射的命令权限。"""

from scripts import dev_verification as verification
from scripts.dev_verification import CONTROLLED_BACKTEST_FIXTURE_COMMAND, controlled_https_command

MEMORY_COMMAND = [
    "python",
    "-m",
    "pytest",
    "-q",
    "-s",
    "packages/backend/tests/application/test_strategy_research_evidence.py::test_actual_strategy_science_producer_report_historical_reader_and_freeze[backtest-owner:memory-completion]",
]


def test_exact_finite_backtest_command_uses_existing_controlled_source_boundary() -> None:
    assert controlled_https_command(CONTROLLED_BACKTEST_FIXTURE_COMMAND)
    assert controlled_https_command(MEMORY_COMMAND)
    for command in [
        [*MEMORY_COMMAND, "-k", "elsewhere"],
        [*MEMORY_COMMAND[:-1], MEMORY_COMMAND[-1].replace("memory-completion", "another")],
        ["python", "elsewhere.py", *MEMORY_COMMAND[3:]],
        ["python3", *MEMORY_COMMAND[1:]],
        [*MEMORY_COMMAND, "--controlled-source-https"],
        ["python", "test-results/wrapper.py"],
    ]:
        assert not controlled_https_command(command), command


def test_host_and_inside_refuse_missing_controlled_mode_before_resource_access() -> None:
    for command in [CONTROLLED_BACKTEST_FIXTURE_COMMAND, MEMORY_COMMAND]:
        for runner in [
            lambda command=command: verification.run_inside(command, controlled_source_https=False),
            lambda command=command: verification.run_host(
                "run", command, web=False, rebuild=False, reservation={}, controlled_source_https=False
            ),
        ]:
            try:
                runner()
            except ValueError as error:
                assert str(error) == "DEV_CONTROLLED_HTTPS_COMMAND_REFUSED"
            else:
                raise AssertionError("missing controlled mode must fail before resource access")
