"""Orthogonal streaming phase and data-state models."""

from enum import StrEnum


class OnlyStreamingPhase(StrEnum):
    CREATED = "CREATED"
    SUBSCRIBING = "SUBSCRIBING"
    BOOTSTRAP = "BOOTSTRAP"
    CATCH_UP = "CATCH_UP"
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class OnlyStreamingDataState(StrEnum):
    BOOTSTRAPPING = "BOOTSTRAPPING"
    CATCHING_UP = "CATCHING_UP"
    LIVE = "LIVE"
    IDLE = "IDLE"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    FAILED = "FAILED"
