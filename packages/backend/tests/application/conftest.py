"""Reuse the canonical, guarded, serial PostgreSQL test namespace."""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.backend.tests.application.support.native_probe import build_native_probe

from packages.backend.tests.postgres_fixtures import postgres_dsn

__all__ = ["postgres_dsn"]



@pytest.fixture(scope="session")
def native_probe() -> Path:
    return build_native_probe()


@pytest.fixture(scope="session")
def native_release_probe() -> Path:
    return build_native_probe(release=True)
