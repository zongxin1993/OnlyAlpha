from pathlib import Path

import pytest

from scripts.project_state import (
    PROJECTION_PATHS,
    ROOT,
    ProjectStateError,
    load_state,
    projection_drift,
    render_projection,
    start_increment,
    verify_increment,
)

pytestmark = pytest.mark.architecture


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
    state = load_state()

    with pytest.raises(ProjectStateError, match="next authorized increment"):
        start_increment(state, "P9.K.7")

    started = start_increment(state, "P9.K.6")

    assert started.last_verified_increment == "P9.K.5"
    assert started.active_increment == "P9.K.6"
    assert started.active_name == "External Client Migration"
    assert started.active_state == "IN_PROGRESS"
    assert started.next_authorized_increment == ""


def test_only_active_increment_can_be_verified_and_authorize_successor() -> None:
    started = start_increment(load_state(), "P9.K.6")

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
