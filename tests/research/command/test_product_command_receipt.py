from datetime import UTC, datetime

import pytest

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
    only_cancel_research_run_command_fingerprint,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.command.model import OnlyResearchSubmitCommand
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    only_research_execution_generation_fingerprint,
)
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


def test_create_fingerprint_binds_authoritative_provenance_and_excludes_locator() -> None:
    strict = OnlyResearchSpecification.from_dict(specification().to_dict())
    identity = {
        "experiment_id": "exp-" + "a" * 32,
        "source_repository": "OnlyAlpha-alpha",
        "source_revision": "1" * 40,
        "source_tree": "2" * 40,
        "candidate_provider_id": "private.onlyalpha.alpha.candidate",
        "candidate_provider_version": "candidate-1",
        "candidate_provider_content_fingerprint": "3" * 64,
        "catalog_generation_fingerprint": "4" * 64,
    }
    provenance = OnlyResearchAuthoringProvenance(
        schema_version=1,
        **identity,
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(**identity),
        source_locator="/one",
    )
    first = OnlyResearchSubmitCommand(COMMAND_ID, strict, provenance)
    second = OnlyResearchSubmitCommand(
        COMMAND_ID,
        strict,
        OnlyResearchAuthoringProvenance.from_dict({**provenance.to_dict(), "source_locator": "/two"}),
    )
    changed_identity = {**identity, "source_revision": "5" * 40}
    changed = OnlyResearchSubmitCommand(
        COMMAND_ID,
        strict,
        OnlyResearchAuthoringProvenance.from_dict(
            {
                **provenance.to_dict(),
                "source_revision": "5" * 40,
                "execution_generation_fingerprint": only_research_execution_generation_fingerprint(**changed_identity),
            }
        ),
    )
    assert first.command_fingerprint == second.command_fingerprint
    assert first.command_fingerprint != changed.command_fingerprint


def test_cancel_fingerprint_depends_only_on_exact_target_run() -> None:
    expected = only_cancel_research_run_command_fingerprint(RUN_ID)
    assert expected == only_canonical_fingerprint({"run_id": RUN_ID})
    assert expected != only_cancel_research_run_command_fingerprint("00000000-0000-4000-8000-000000000511")


def test_product_command_admission_v1_is_exact_and_contains_only_identity_binding() -> None:
    admission = OnlyProductCommandAdmissionV1(
        COMMAND_ID,
        OnlyProductCommandKind.CREATE_RESEARCH_RUN,
        "a" * 64,
    )
    assert admission.schema_version == 1
    assert set(admission.__dataclass_fields__) == {
        "command_id",
        "command_kind",
        "command_fingerprint",
        "schema_version",
    }
    with pytest.raises(ValueError, match="lower-case SHA256"):
        OnlyProductCommandAdmissionV1(COMMAND_ID, OnlyProductCommandKind.CREATE_RESEARCH_RUN, "A" * 64)
    with pytest.raises(ValueError, match="schema version"):
        OnlyProductCommandAdmissionV1(COMMAND_ID, OnlyProductCommandKind.CREATE_RESEARCH_RUN, "a" * 64, 2)
    with pytest.raises(ValueError, match="kind"):
        OnlyProductCommandAdmissionV1(COMMAND_ID, "CREATE_RESEARCH_RUN", "a" * 64)  # type: ignore[arg-type]


def test_search_product_vocabulary_is_representation_only_and_uses_sha256_outcome() -> None:
    assert {
        OnlyProductCommandKind.CREATE_SYMBOLIC_SEARCH_EXPERIMENT,
        OnlyProductCommandKind.CREATE_PARAMETER_SEARCH_EXPERIMENT,
        OnlyProductCommandKind.ADVANCE_SEARCH_EXPERIMENT,
    } <= set(OnlyProductCommandKind)
    expected = OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.SEARCH_EXPERIMENT, "b" * 64)
    assert expected.outcome_id == "b" * 64
    with pytest.raises(ValueError, match="lower-case SHA256"):
        OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.SEARCH_EXPERIMENT, COMMAND_ID.value)
