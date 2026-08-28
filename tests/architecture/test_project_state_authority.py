from dataclasses import replace
from pathlib import Path

import pytest

from scripts.project_state import (
    P9_K_CLOSED_STATUS,
    PROJECTION_PATHS,
    ROOT,
    ProjectState,
    ProjectStateError,
    load_state,
    projection_drift,
    render_projection,
    start_increment,
    verify_increment,
)

pytestmark = pytest.mark.architecture


def _k6_ready_state() -> ProjectState:
    return replace(
        load_state(),
        last_verified_increment="P9.K.5",
        last_verified_name="Closure — Functional Correctness / Coverage Evidence Separation",
        last_verified_state="TASK COMPLETE / VERIFIED",
        active_increment="",
        active_name="",
        active_state="",
        next_authorized_increment="P9.K.6",
        next_authorized_name="External Client Migration",
        next_authorized_state="IMPLEMENTATION READY",
    )


def test_project_state_authority_is_valid_and_all_projections_are_exact() -> None:
    state = load_state()

    assert projection_drift(state) == ()


def test_project_state_projection_render_is_idempotent() -> None:
    state = load_state()

    for relative in PROJECTION_PATHS:
        current = (ROOT / relative).read_text(encoding="utf-8")
        rendered = render_projection(relative, current, state)
        assert render_projection(relative, rendered, state) == rendered


def test_project_state_authority_is_the_only_machine_writable_current_state() -> None:
    authority = ROOT / Path("project-state.toml")
    source = authority.read_text(encoding="utf-8")

    assert "sole authoring authority" in source
    assert "last_verified_increment" in source
    assert "active_increment" in source
    assert "next_authorized_increment" in source


def test_only_exactly_authorized_next_increment_can_start() -> None:
    state = _k6_ready_state()

    with pytest.raises(ProjectStateError, match="next authorized increment"):
        start_increment(state, "P9.K.7")

    started = start_increment(state, "P9.K.6")

    assert started.last_verified_increment == "P9.K.5"
    assert started.active_increment == "P9.K.6"
    assert started.active_name == "External Client Migration"
    assert started.active_state == "IN_PROGRESS"
    assert started.next_authorized_increment == ""


def test_only_active_increment_can_be_verified_and_authorize_successor() -> None:
    started = start_increment(_k6_ready_state(), "P9.K.6")

    with pytest.raises(ProjectStateError, match="active increment"):
        verify_increment(started, "P9.K.7", next_id="P9.K.8", next_name="Seal Kernel")

    verified = verify_increment(
        started,
        "P9.K.6",
        next_id="P9.K.7",
        next_name="Remote Protocol Foundation",
    )

    assert verified.last_verified_increment == "P9.K.6"
    assert verified.last_verified_name == "External Client Migration"
    assert verified.last_verified_state == "TASK COMPLETE / VERIFIED"
    assert verified.active_increment == ""
    assert verified.next_authorized_increment == "P9.K.7"
    assert verified.next_authorized_name == "Remote Protocol Foundation"
    assert verified.next_authorized_state == "IMPLEMENTATION READY"


def test_k8_verification_closes_p9_k_and_unblocks_p9_1() -> None:
    active = replace(
        load_state(),
        last_verified_increment="P9.K.7",
        last_verified_name="Remote Protocol Foundation",
        last_verified_state="TASK COMPLETE / VERIFIED",
        active_increment="P9.K.8",
        active_name="Seal Kernel",
        active_state="IN_PROGRESS",
        next_authorized_increment="",
        next_authorized_name="",
        next_authorized_state="",
        p9_1_plus_status="BLOCKED until P9.K closure",
    )

    verified = verify_increment(
        active,
        "P9.K.8",
        next_id="P9.1",
        next_name="Crypto Market Product & Binance Reference Authority",
    )

    assert verified.last_verified_increment == "P9.K.8"
    assert verified.next_authorized_increment == "P9.1"
    assert verified.next_authorized_name == "Crypto Market Product & Binance Reference Authority"
    assert verified.p9_1_plus_status == P9_K_CLOSED_STATUS
