from pathlib import Path

import pytest

from scripts.project_state import PROJECTION_PATHS, ROOT, load_state, projection_drift, render_projection

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
