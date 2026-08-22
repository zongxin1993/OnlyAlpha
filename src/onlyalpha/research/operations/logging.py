"""Small stable structured-event layer over the standard logging authority."""

from __future__ import annotations

import json
import logging

from onlyalpha.core.clock import only_system_utc_now


def only_log_research_operational_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: object,
) -> None:
    payload = {
        "timestamp": only_system_utc_now().isoformat(),
        "level": logging.getLevelName(level),
        "component": "research",
        "event": event,
        **{key: value for key, value in fields.items() if value is not None},
    }
    logger.log(level, json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


__all__ = ["only_log_research_operational_event"]
