from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.application.market_data_product import OnlyMarketDataSourceReferenceV1, OnlyMarketDataSourceSelectionV1
from onlyalpha.application.source_read_access import (
    OnlySourceReadAccessError,
    OnlySourceReadAuthority,
    OnlySourceReadGrant,
    OnlySourceReadPermission,
    OnlySourceReadSession,
)
from onlyalpha.market_data.durable.range_query import OnlyBarWindowAnchorKind
from tests.application.test_market_data_product import INSTRUMENT, TYPE_ID, _range, _reference, _service

TOKEN = "ee" * 32


def _authority(reference: OnlyMarketDataSourceReferenceV1, **changes: object) -> OnlySourceReadAuthority:
    grant = OnlySourceReadGrant(
        reference.integration_id,
        reference.integration_revision_fingerprint,
        TYPE_ID,
        "test.spot.live",
        "LIVE",
        (OnlySourceReadPermission.CLOSED_HISTORY, OnlySourceReadPermission.REALTIME_PREVIEW),
    )
    return OnlySourceReadAuthority("operator", hashlib.sha256(TOKEN.encode()).hexdigest(), (replace(grant, **changes),))


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer",
        "Bearer bad",
        "bearer " + TOKEN,
        "Bearer " + "00" * 32,
        "Bearer " + TOKEN + " ",
        "Bearer " + "a" * 4096,
    ],
)
def test_invalid_bearer_never_issues_a_subject(header: str) -> None:
    authority = _authority(OnlyMarketDataSourceReferenceV1("integration", "a" * 64, TYPE_ID))
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_UNAUTHORIZED") as error:
        authority.authenticate(header)
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize(
    "dimension,value",
    [
        ("integration_id", "another"),
        ("integration_revision_fingerprint", "b" * 64),
        ("expected_type_id", "another.type"),
        ("source_id", "another.source"),
        ("environment", "SIM"),
    ],
)
def test_wrong_grant_dimension_fails_before_owning_instrument_io(tmp_path: Path, dimension: str, value: str) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    authority = _authority(reference, **{dimension: value})
    session = authority.authenticate("Bearer " + TOKEN)
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_FORBIDDEN"):
        harness.service.list_instruments(reference, read_session=session)
    assert harness.provider.reference_lookups == 0
    assert harness.catalog.mutations == 0


def test_whole_owner_and_issuance_mutations_do_not_authenticate() -> None:
    reference = OnlyMarketDataSourceReferenceV1("integration", "a" * 64, TYPE_ID)
    owner = _authority(reference)
    session = owner.authenticate("Bearer " + TOKEN)
    other = _authority(reference)
    for mutated in (OnlySourceReadSession(owner, object()), replace(session, authority=other)):
        with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_UNAUTHORIZED"):
            mutated.check_active()
    owner.withdraw()
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_UNAUTHORIZED"):
        session.check_active()
    with pytest.raises(OnlySourceReadAccessError):
        owner.authenticate("Bearer " + TOKEN)


def test_duplicate_owner_grants_and_missing_permission_are_rejected() -> None:
    reference = OnlyMarketDataSourceReferenceV1("integration", "a" * 64, TYPE_ID)
    owner = _authority(reference)
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_CONFIG_INVALID"):
        OnlySourceReadAuthority("operator", "a" * 64, owner.grants * 2)
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_CONFIG_INVALID"):
        replace(owner.grants[0], permissions=())
    historical = _authority(reference, permissions=(OnlySourceReadPermission.CLOSED_HISTORY,))
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_FORBIDDEN"):
        historical.authenticate("Bearer " + TOKEN).require_reference(
            reference, OnlySourceReadPermission.REALTIME_PREVIEW
        )


def test_verified_empty_grant_snapshot_authenticates_but_authorizes_no_source() -> None:
    authority = OnlySourceReadAuthority("local-developer", hashlib.sha256(TOKEN.encode()).hexdigest(), ())
    session = authority.authenticate("Bearer " + TOKEN)
    session.check_active()
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_FORBIDDEN"):
        session.require_reference(
            OnlyMarketDataSourceReferenceV1("integration", "a" * 64, TYPE_ID),
            OnlySourceReadPermission.CLOSED_HISTORY,
        )


def test_source_listing_filters_exact_grants_before_resolving_unauthorized_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _service(tmp_path)
    denied = _authority(_reference("b" * 64)).authenticate("Bearer " + TOKEN)
    calls: list[object] = []
    original = harness.service.resolve_runtime

    def resolve(reference: OnlyMarketDataSourceReferenceV1):
        calls.append(reference)
        return original(reference)

    monkeypatch.setattr(harness.service, "resolve_runtime", resolve)
    assert harness.service.list_sources(read_session=denied) == ()
    assert calls == []
    assert harness.provider.reference_lookups == 0


def test_authorized_owning_history_reads_preserve_exact_market_inventory(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start, end = _range()
    harness.service.acquire_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start, end_ns=end)
    before = (
        harness.catalog.mutations,
        harness.service._facts.writes,
        tuple(sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())),
    )
    session = _authority(reference).authenticate("Bearer " + TOKEN)
    assert harness.service.list_sources(read_session=session)[0].source_id == "test.spot.live"
    assert (
        harness.service.list_instruments(reference, read_session=session).source_selection.source_id == "test.spot.live"
    )
    projection = harness.service.query_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        anchor_kind=OnlyBarWindowAnchorKind.BEFORE_TIME,
        before_ns=end,
        target_bar_count=2,
        read_session=session,
    )
    assert len(projection.bars) == 2
    assert projection.coverage.status == "COMPLETE"
    after = (
        harness.catalog.mutations,
        harness.service._facts.writes,
        tuple(sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())),
    )
    assert before == after


@pytest.mark.parametrize(
    "dimension,value",
    [("source_id", "another.source"), ("environment", "SIM"), ("integration_revision_fingerprint", "b" * 64)],
)
def test_admitted_command_source_proof_fails_before_any_durable_write(
    tmp_path: Path, dimension: str, value: str
) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    session = _authority(reference, **{dimension: value}).authenticate("Bearer " + TOKEN)
    start, end = _range()
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_FORBIDDEN"):
        harness.service.acquire_bars(
            reference, instrument_id=str(INSTRUMENT), start_ns=start, end_ns=end, source_session=session
        )
    assert harness.catalog.mutations == 0
    assert harness.service._facts.writes == 0
    assert harness.provider.reference_lookups == 0


def test_withdrawn_command_source_proof_cannot_start_acquisition(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    authority = _authority(reference)
    session = authority.authenticate("Bearer " + TOKEN)
    authority.withdraw()
    start, end = _range()
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_UNAUTHORIZED"):
        harness.service.acquire_bars(
            reference, instrument_id=str(INSTRUMENT), start_ns=start, end_ns=end, source_session=session
        )
    assert harness.catalog.mutations == 0
    assert harness.service._facts.writes == 0


def test_missing_or_different_leaf_proof_never_becomes_authorized() -> None:
    reference = OnlyMarketDataSourceReferenceV1("integration", "a" * 64, TYPE_ID)
    session = _authority(reference).authenticate("Bearer " + TOKEN)
    correct = OnlyMarketDataSourceSelectionV1("integration", "a" * 64, TYPE_ID, "test.spot.live", "LIVE")
    session.require_selection(correct, OnlySourceReadPermission.CLOSED_HISTORY)
    for changed in (replace(correct, source_id=""), replace(correct, environment="")):
        with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_PROOF_UNAVAILABLE"):
            session.require_selection(changed, OnlySourceReadPermission.CLOSED_HISTORY)
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_FORBIDDEN"):
        session.require_selection(replace(correct, source_id="different"), OnlySourceReadPermission.CLOSED_HISTORY)
