from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from hypothesis import settings

settings.register_profile(
    "dev",
    max_examples=100,
    deadline=None,
    stateful_step_count=50,
)


settings.register_profile(
    "ci",
    max_examples=300,
    deadline=None,
    stateful_step_count=75,
)


settings.register_profile(
    "exhaustive",
    max_examples=2000,
    deadline=None,
    stateful_step_count=150,
)


settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture
def source_checkout_parameter_build_provenance_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give Parameter Search source-checkout tests one deterministic test provenance."""

    import onlyalpha.research.search.parameter.algorithm as parameter_algorithm

    monkeypatch.setattr(
        parameter_algorithm,
        "only_packaged_build_provenance",
        lambda: SimpleNamespace(source_revision="1" * 40),
    )
