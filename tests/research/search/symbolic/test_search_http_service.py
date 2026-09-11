from __future__ import annotations

from pathlib import Path
from typing import cast

from onlyalpha_http_server.search.schema import SearchAdvanceRequestDto, SymbolicSearchSubmitRequestDto
from onlyalpha_http_server.search.service import OnlySearchProductHttpServiceV1

from onlyalpha.application.product_boundary import OnlyResearchProductBoundary
from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlyGetSearchExperimentV1,
    OnlyGetSearchIterationLedgerV1,
    OnlyGetSearchTerminalDecisionV1,
)
from onlyalpha.kernel.command import OnlyProductCommandDispatcher
from onlyalpha.kernel.query import OnlyProductQueryDispatcher

from .test_search_product_adapter import _case, _command_id


class _Commands:
    def __init__(self, service) -> None:  # type: ignore[no-untyped-def]
        self.service = service
        self.observed: list[object] = []

    def dispatch(self, command):  # type: ignore[no-untyped-def]
        self.observed.append(command)
        if isinstance(command, OnlyAdvanceSearchExperimentV1):
            return self.service.advance(command)
        return self.service.submit(command)


class _Queries:
    def __init__(self, service) -> None:  # type: ignore[no-untyped-def]
        self.service = service

    def dispatch(self, query):  # type: ignore[no-untyped-def]
        if isinstance(query, OnlyGetSearchExperimentV1):
            return self.service.get_experiment(query)
        if isinstance(query, OnlyGetSearchIterationLedgerV1):
            return self.service.get_ledger(query)
        if isinstance(query, OnlyGetSearchTerminalDecisionV1):
            return self.service.get_terminal(query)
        raise TypeError(query)


def test_http_service_preserves_command_identity_and_delegates_to_owning_search_authorities(tmp_path: Path) -> None:
    commands, queries, _authority, _research, template = _case(tmp_path)
    command_dispatch = _Commands(commands)
    product = OnlyResearchProductBoundary(
        cast(OnlyProductCommandDispatcher, command_dispatch),
        cast(OnlyProductQueryDispatcher, _Queries(queries)),
    )
    service = OnlySearchProductHttpServiceV1(product)
    payload = template.intent_dict()
    del payload["method"]
    request = SymbolicSearchSubmitRequestDto.model_validate(payload)
    command_id = _command_id().value
    submitted = service.submit_symbolic(command_id, request)
    assert submitted.product_command_id == command_id
    assert command_dispatch.observed[0].command_id.value == command_id  # type: ignore[attr-defined]
    assert len(submitted.experiment_fingerprint) == 64

    experiment = service.get_experiment(submitted.experiment_fingerprint)
    ledger = service.get_ledger(submitted.experiment_fingerprint)
    terminal = service.get_terminal(submitted.experiment_fingerprint)
    assert experiment.experiment_fingerprint == submitted.experiment_fingerprint
    assert ledger.experiment_fingerprint == submitted.experiment_fingerprint
    assert terminal.experiment_fingerprint == submitted.experiment_fingerprint

    advance_id = "00000000-0000-4000-8000-000000000111"
    advance = service.advance_symbolic(
        advance_id,
        SearchAdvanceRequestDto(
            schema_version=1,
            method="SYMBOLIC",
            operation="ADVANCE_ONE_SYMBOLIC_OCCURRENCE",
            experiment_fingerprint=submitted.experiment_fingerprint,
            expected_state=submitted.ledger["expected_state"],
        ),
    )
    assert advance.product_command_id == advance_id
    assert command_dispatch.observed[-1].command_id.value == advance_id  # type: ignore[attr-defined]
