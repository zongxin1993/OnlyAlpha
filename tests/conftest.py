from __future__ import annotations

import os

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
