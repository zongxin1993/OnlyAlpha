from __future__ import annotations

from fastapi import FastAPI
from hypothesis import settings
import pytest

from onlyalpha.research.operations.readiness import OnlyResearchReadiness, OnlyResearchReadinessStatus
from onlyalpha_http_server.health import create_health_router

schemathesis = pytest.importorskip("schemathesis")

pytestmark = pytest.mark.contract


class _ReadyProbe:
    def inspect(self) -> OnlyResearchReadiness:
        return OnlyResearchReadiness(OnlyResearchReadinessStatus.READY, ())


class _AvailableExecutionCapacity:
    def has_fresh_worker(self) -> bool:
        return True


def _health_app() -> FastAPI:
    app = FastAPI(title="OnlyAlpha Health Contract Probe")
    app.include_router(create_health_router(_ReadyProbe(), _AvailableExecutionCapacity()))
    return app


schema = schemathesis.openapi.from_asgi("/openapi.json", _health_app())


@schema.parametrize()
@settings(max_examples=10, deadline=None)
def test_health_contract_generated_cases(case) -> None:
    case.call_and_validate()
