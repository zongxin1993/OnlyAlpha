"""Policies shared by frozen Bar recipes and construction executors."""

from enum import StrEnum


class OnlyBarMissingPolicy(StrEnum):
    REJECT = "REJECT"
    SKIP_WINDOW = "SKIP_WINDOW"


class OnlyBarIncompletePolicy(StrEnum):
    DROP = "DROP"
    REJECT = "REJECT"
