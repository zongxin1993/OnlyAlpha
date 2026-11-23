"""精确受控 Backtest 场景入口；不扩大 root 映射的命令权限。"""

from scripts import dev_verification as verification
from scripts.dev_verification import (
    CONTROLLED_BACKTEST_FIXTURE_COMMAND,
    controlled_backtest_fixture_command,
    controlled_https_command,
)

MEMORY_COMMAND = [
    "python",
    "-m",
    "pytest",
    "-q",
    "-s",
    "packages/backend/tests/application/test_strategy_research_evidence.py::test_actual_strategy_science_producer_report_historical_reader_and_freeze[backtest-owner:memory-completion]",
]

# 负责人批准「仅此用例」：只登记这一个完整 pytest 节点的精确 argv，
# 使 120 秒有限发布用例能在既有受控回环装配下启动正式 Host。
PUBLICATION_COMMAND = [
    "python",
    "-m",
    "pytest",
    "-q",
    "packages/backend/tests/application/test_backtest_worker_publication.py::test_actual_backtest_scheduler_publishes_original_run_without_file_results",
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


def test_exact_publication_node_command_uses_existing_controlled_source_boundary() -> None:
    assert controlled_https_command(PUBLICATION_COMMAND)
    whole_file = ["python", "-m", "pytest", "-q", PUBLICATION_COMMAND[3].split("::", 1)[0]]
    for command in [
        whole_file,
        [*PUBLICATION_COMMAND, "-k", "elsewhere"],
        [*PUBLICATION_COMMAND, "-s"],
        [*PUBLICATION_COMMAND, "--deselect", PUBLICATION_COMMAND[3]],
        PUBLICATION_COMMAND[:-1] + [PUBLICATION_COMMAND[-1].rsplit("_", 1)[0]],
        [*PUBLICATION_COMMAND[:-1], PUBLICATION_COMMAND[-1].replace("test_actual_", "test_other_")],
        ["python", "-m", "pytest", PUBLICATION_COMMAND[3]],
        ["python3", *PUBLICATION_COMMAND[1:]],
        ["python", "-m", "pytest", "-q", "-x", PUBLICATION_COMMAND[3]],
        ["python", "elsewhere.py", *PUBLICATION_COMMAND[3:]],
        [*PUBLICATION_COMMAND, "--controlled-source-https"],
        [*CONTROLLED_BACKTEST_FIXTURE_COMMAND, *PUBLICATION_COMMAND[3:]],
    ]:
        assert not controlled_https_command(command), command


def test_existing_controlled_commands_stay_exact_after_publication_entry() -> None:
    assert CONTROLLED_BACKTEST_FIXTURE_COMMAND != PUBLICATION_COMMAND
    assert MEMORY_COMMAND != PUBLICATION_COMMAND
    assert controlled_backtest_fixture_command(PUBLICATION_COMMAND)
    assert not controlled_backtest_fixture_command([*PUBLICATION_COMMAND, "-s"])
    assert controlled_backtest_fixture_command(CONTROLLED_BACKTEST_FIXTURE_COMMAND)
    assert controlled_backtest_fixture_command(MEMORY_COMMAND)
    assert not controlled_backtest_fixture_command(PUBLICATION_COMMAND[:-1])


def test_host_and_inside_refuse_missing_controlled_mode_before_resource_access() -> None:
    for command in [CONTROLLED_BACKTEST_FIXTURE_COMMAND, MEMORY_COMMAND, PUBLICATION_COMMAND]:
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
