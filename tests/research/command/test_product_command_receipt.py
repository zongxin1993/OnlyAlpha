from datetime import UTC, datetime

import pytest

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
    only_cancel_research_run_command_fingerprint,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.command.model import OnlyResearchSubmitCommand
from onlyalpha.research.specification.model import OnlyResearchSpecification
from tests.research.specification.support import specification

NOW = datetime(2026, 8, 27, tzinfo=UTC)
COMMAND_ID = OnlyProductCommandId("00000000-0000-4000-8000-000000000501")
RUN_ID = "00000000-0000-4000-8000-000000000510"


def test_product_command_id_and_receipt_are_strict_operational_values() -> None:
    with pytest.raises(ValueError, match="canonical UUID4"):
        OnlyProductCommandId("not-a-uuid")
    with pytest.raises(ValueError, match="lowercase SHA256"):
        OnlyProductCommandReceipt(
            COMMAND_ID,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            "A" * 64,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, RUN_ID),
            NOW,
        )
    with pytest.raises(ValueError, match="schema version"):
        OnlyProductCommandReceipt(
            COMMAND_ID,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            "a" * 64,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, RUN_ID),
            NOW,
            schema_version=2,
        )


def test_create_fingerprint_bytes_remain_the_legacy_specification_shape() -> None:
    strict = OnlyResearchSpecification.from_dict(specification().to_dict())
    command = OnlyResearchSubmitCommand(COMMAND_ID, strict)
    assert command.command_fingerprint == only_canonical_fingerprint({"specification": strict.to_dict()})
    assert command.command_fingerprint != only_canonical_fingerprint(
        {"command_kind": OnlyProductCommandKind.CREATE_RESEARCH_RUN.value, "specification": strict.to_dict()}
    )


def test_cancel_fingerprint_depends_only_on_exact_target_run() -> None:
    expected = only_cancel_research_run_command_fingerprint(RUN_ID)
    assert expected == only_canonical_fingerprint({"run_id": RUN_ID})
    assert expected != only_cancel_research_run_command_fingerprint("00000000-0000-4000-8000-000000000511")
