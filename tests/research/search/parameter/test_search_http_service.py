from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from onlyalpha_http_server.search.schema import ParameterSearchSubmitRequestDto, SearchAdvanceRequestDto
from onlyalpha_http_server.search.service import OnlySearchProductHttpServiceV1

from onlyalpha.application.product_boundary import OnlyResearchProductBoundary
from onlyalpha.canonical import only_canonical_json
from onlyalpha.kernel.command import OnlyProductCommandDispatcher
from onlyalpha.kernel.query import OnlyProductQueryDispatcher
from tests.research.search.symbolic.test_search_http_service import _Commands, _Queries

from .test_search_product_adapter import _product_case


def test_parameter_http_service_preserves_command_identity_and_uses_real_product_authority(
    tmp_path: Path,
    source_checkout_parameter_build_provenance_stub: None,
) -> None:
    commands, queries, _authority, _runs, _research, template, _adapter = _product_case(tmp_path)
    command_dispatch = _Commands(commands)
    product = OnlyResearchProductBoundary(
        cast(OnlyProductCommandDispatcher, command_dispatch),
        cast(OnlyProductQueryDispatcher, _Queries(queries)),
    )
    service = OnlySearchProductHttpServiceV1(product)
    payload = json.loads(only_canonical_json(template.intent_dict()))
    del payload["method"]
    request = ParameterSearchSubmitRequestDto.model_validate(payload)
    command_id = template.command_id.value

    submitted = service.submit_parameter(command_id, request)
    assert submitted.product_command_id == command_id
    assert command_dispatch.observed[0].command_id.value == command_id  # type: ignore[attr-defined]
    assert submitted.method == "PARAMETER"

    advance_id = "00000000-0000-4000-8000-000000000112"
    advanced = service.advance_parameter(
        advance_id,
        SearchAdvanceRequestDto(
            schema_version=1,
            method="PARAMETER",
            operation="ADVANCE_ONE_PARAMETER_DECISION",
            experiment_fingerprint=submitted.experiment_fingerprint,
            expected_state=submitted.ledger["expected_state"],
        ),
    )
    assert advanced.product_command_id == advance_id
    assert command_dispatch.observed[-1].command_id.value == advance_id  # type: ignore[attr-defined]
