"""Reuse the canonical, guarded, serial PostgreSQL test namespace."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from packages.backend.tests.application.support.native_probe import build_native_probe
from packages.backend.tests.postgres_fixtures import postgres_dsn

__all__ = ["postgres_dsn"]

_BACKTEST_OWNER_PROBE = pytest.StashKey[Path]()
_BACKTEST_WEB_ASSETS = pytest.StashKey[Path]()


def pytest_collection_finish(session: pytest.Session) -> None:
    if session.config.option.collectonly or session.testsfailed:
        return
    backtest_publication = Path(__file__).with_name("test_backtest_worker_publication.py")
    research_publication = Path(__file__).with_name("test_research_worker_publication.py")
    research_target = Path(__file__).with_name("test_strategy_research_evidence.py")
    needs_web = any(
        item.path == backtest_publication
        or (
            isinstance(item, pytest.Function)
            and item.path == research_target
            and hasattr(item, "callspec")
            and str(item.callspec.params.get("mode", "")).startswith("backtest-owner:")
        )
        for item in session.items
    )
    if not (needs_web or any(item.path == research_publication for item in session.items)):
        return

    from packages.backend.tests.application.test_strategy_research_evidence import _build_strategy_evidence_owner_binary

    # pytest-timeout 在 fixture setup 前启动，编译须在 collection 结束时完成。
    session.config.stash[_BACKTEST_OWNER_PROBE] = _build_strategy_evidence_owner_binary(
        release=True, build_timeout=None, target_name="backtest_owner_probe"
    )
    if needs_web:
        from packages.backend.tests.application.backtest_native_host import build_web_assets
        from scripts.native_http_contract import native_executable

        native_executable(release=True)
        web_build = TemporaryDirectory(prefix="onlyalpha-backtest-publication-")
        session.config.add_cleanup(web_build.cleanup)
        session.config.stash[_BACKTEST_WEB_ASSETS] = build_web_assets(Path(web_build.name))


@pytest.fixture(scope="session")
def backtest_fault_probe(pytestconfig: pytest.Config) -> Path:
    return pytestconfig.stash[_BACKTEST_OWNER_PROBE]


@pytest.fixture(scope="session")
def backtest_web_assets(pytestconfig: pytest.Config) -> Path:
    return pytestconfig.stash[_BACKTEST_WEB_ASSETS]


@pytest.fixture(scope="session")
def native_probe() -> Path:
    return build_native_probe()


@pytest.fixture(scope="session")
def native_release_probe() -> Path:
    return build_native_probe(release=True)
