from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = Path("project-state.toml")
PROJECTION_PATHS = (
    Path("README.md"),
    Path("docs/roadmap.md"),
    Path("docs/p9_k_stateful_kernel_protocol_boundary.md"),
)
P9_K_CLOSED_STATUS = "P9.K = CLOSED; P9.1+ = UNBLOCKED"


class ProjectStateError(RuntimeError):
    """The project-state authority or one of its projections is invalid."""


@dataclass(frozen=True, slots=True)
class ProjectState:
    schema_version: int
    milestone: str
    milestone_state: str
    last_verified_increment: str
    last_verified_name: str
    last_verified_state: str
    active_increment: str
    active_name: str
    active_state: str
    next_authorized_increment: str
    next_authorized_name: str
    next_authorized_state: str
    p9_1_plus_status: str
    latest_certified_increment: str
    latest_certified_state: str
    latest_certified_subject_sha: str
    latest_certified_run: int
    latest_certified_verdict: str

    @property
    def current_increment(self) -> str:
        return self.active_increment or self.last_verified_increment

    @property
    def current_name(self) -> str:
        return self.active_name or self.last_verified_name

    @property
    def current_state(self) -> str:
        return self.active_state or self.last_verified_state


def _require_string(mapping: Mapping[str, object], key: str, *, allow_empty: bool = False) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise ProjectStateError(f"project-state field {key!r} must be a string")
    if not allow_empty and not value.strip():
        raise ProjectStateError(f"project-state field {key!r} must be non-empty")
    if value != value.strip():
        raise ProjectStateError(f"project-state field {key!r} must not contain surrounding whitespace")
    return value


def _require_table(document: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise ProjectStateError(f"project-state table [{key}] is required")
    return value


def load_state(root: Path = ROOT) -> ProjectState:
    path = root / AUTHORITY_PATH
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProjectStateError(f"cannot load {AUTHORITY_PATH}: {exc}") from exc

    schema_version = document.get("schema_version")
    if schema_version != 1:
        raise ProjectStateError("project-state schema_version must be exactly 1")

    project = _require_table(document, "project")
    development = _require_table(document, "development")
    certification = _require_table(document, "certification")

    latest_run = certification.get("latest_run")
    if not isinstance(latest_run, int) or latest_run <= 0:
        raise ProjectStateError("project-state certification.latest_run must be a positive integer")

    state = ProjectState(
        schema_version=1,
        milestone=_require_string(project, "milestone"),
        milestone_state=_require_string(project, "milestone_state"),
        last_verified_increment=_require_string(development, "last_verified_increment"),
        last_verified_name=_require_string(development, "last_verified_name"),
        last_verified_state=_require_string(development, "last_verified_state"),
        active_increment=_require_string(development, "active_increment", allow_empty=True),
        active_name=_require_string(development, "active_name", allow_empty=True),
        active_state=_require_string(development, "active_state", allow_empty=True),
        next_authorized_increment=_require_string(development, "next_authorized_increment", allow_empty=True),
        next_authorized_name=_require_string(development, "next_authorized_name", allow_empty=True),
        next_authorized_state=_require_string(development, "next_authorized_state", allow_empty=True),
        p9_1_plus_status=_require_string(development, "p9_1_plus_status"),
        latest_certified_increment=_require_string(certification, "latest_increment"),
        latest_certified_state=_require_string(certification, "latest_state"),
        latest_certified_subject_sha=_require_string(certification, "latest_subject_sha"),
        latest_certified_run=latest_run,
        latest_certified_verdict=_require_string(certification, "latest_verdict"),
    )
    _validate_state(state)
    return state


def _validate_state(state: ProjectState) -> None:
    active_values = (state.active_increment, state.active_name, state.active_state)
    if any(active_values) and not all(active_values):
        raise ProjectStateError("active increment fields must be either all empty or all non-empty")

    next_values = (
        state.next_authorized_increment,
        state.next_authorized_name,
        state.next_authorized_state,
    )
    if any(next_values) and not all(next_values):
        raise ProjectStateError("next authorized increment fields must be either all empty or all non-empty")
    if (
        state.last_verified_increment == "P9.K.8"
        and state.next_authorized_increment == "P9.1"
        and state.p9_1_plus_status != P9_K_CLOSED_STATUS
    ):
        raise ProjectStateError("verified P9.K.8 must close P9.K and unblock P9.1+")

    if state.active_increment and state.active_increment == state.last_verified_increment:
        raise ProjectStateError("active increment must differ from last verified increment")
    if state.next_authorized_increment and state.next_authorized_increment in {
        state.last_verified_increment,
        state.active_increment,
    }:
        raise ProjectStateError("next authorized increment must be distinct from verified/active increments")

    if not re.fullmatch(r"[0-9a-f]{40}", state.latest_certified_subject_sha):
        raise ProjectStateError("latest certified subject SHA must be 40 lowercase hexadecimal characters")
    if state.latest_certified_verdict != "ACCEPTED":
        raise ProjectStateError("latest certified verdict must be ACCEPTED")


def _plain_current_increment(state: ProjectState) -> str:
    return f"{state.current_increment} {state.current_name} — {state.current_state}"


def _readme_current_increment(state: ProjectState) -> str:
    return f"{state.current_increment} {state.current_name} — **{state.current_state}**"


def _p9_1_plus_sentence(state: ProjectState) -> str:
    return re.sub(r"^BLOCKED\b", "blocked", state.p9_1_plus_status)


def _plain_next_direction(state: ProjectState) -> str:
    if not state.next_authorized_increment:
        return state.p9_1_plus_status
    return (
        f"{state.next_authorized_increment} — {state.next_authorized_name} — "
        f"{state.next_authorized_state}; P9.1+ {_p9_1_plus_sentence(state)}"
    )


def _readme_next_direction(state: ProjectState) -> str:
    if not state.next_authorized_increment:
        return state.p9_1_plus_status
    return (
        f"{state.next_authorized_increment} — {state.next_authorized_name} — "
        f"**{state.next_authorized_state}**; P9.1+ {_p9_1_plus_sentence(state)}"
    )


def _replace_exactly_once(text: str, pattern: str, replacement: str, *, path: Path) -> str:
    rendered, count = re.subn(pattern, replacement, text, count=0, flags=re.MULTILINE)
    if count != 1:
        raise ProjectStateError(f"{path}: expected exactly one projection match for {pattern!r}, got {count}")
    return rendered


def render_projection(path: Path, text: str, state: ProjectState) -> str:
    if path == Path("README.md"):
        rendered = _replace_exactly_once(
            text,
            r"^\| Current milestone \| .+ \|$",
            f"| Current milestone | {state.milestone} — **{state.milestone_state}** |",
            path=path,
        )
        rendered = _replace_exactly_once(
            rendered,
            r"^\| Current increment \| .+ \|$",
            f"| Current increment | {_readme_current_increment(state)} |",
            path=path,
        )
        return _replace_exactly_once(
            rendered,
            r"^\| Next semantic direction \| .+ \|$",
            f"| Next semantic direction | {_readme_next_direction(state)} |",
            path=path,
        )

    if path == Path("docs/roadmap.md"):
        replacements = (
            (r"^Current Milestone: .+$", f"Current Milestone: {state.milestone}"),
            (r"^Milestone State: .+$", f"Milestone State: {state.milestone_state}"),
            (r"^Current Increment: .+$", f"Current Increment: {_plain_current_increment(state)}"),
            (
                r"^Latest Certified Increment: .+$",
                f"Latest Certified Increment: {state.latest_certified_increment} — {state.latest_certified_state}",
            ),
            (r"^Next Semantic Direction: .+$", f"Next Semantic Direction: {_plain_next_direction(state)}"),
            (r"^P9\.1\+ Status: .+$", f"P9.1+ Status: {state.p9_1_plus_status}"),
        )
        rendered = text
        for pattern, replacement in replacements:
            rendered = _replace_exactly_once(rendered, pattern, replacement, path=path)
        return rendered

    if path == Path("docs/p9_k_stateful_kernel_protocol_boundary.md"):
        progress = (
            f"{state.current_increment} {state.current_name} — {state.current_state}; "
            f"{state.next_authorized_increment} — {state.next_authorized_name} — {state.next_authorized_state}"
            if state.next_authorized_increment
            else f"{state.current_increment} {state.current_name} — {state.current_state}"
        )
        return _replace_exactly_once(
            text,
            r"^> Implementation progress: \*\*.*\*\*$",
            f"> Implementation progress: **{progress}**",
            path=path,
        )

    raise ProjectStateError(f"unsupported project-state projection: {path}")


def projection_drift(state: ProjectState, root: Path = ROOT) -> tuple[Path, ...]:
    drift: list[Path] = []
    for relative in PROJECTION_PATHS:
        path = root / relative
        try:
            current = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProjectStateError(f"cannot read project-state projection {relative}: {exc}") from exc
        if render_projection(relative, current, state) != current:
            drift.append(relative)
    return tuple(drift)


def render_all(state: ProjectState, root: Path = ROOT) -> tuple[Path, ...]:
    changed: list[Path] = []
    for relative in PROJECTION_PATHS:
        path = root / relative
        current = path.read_text(encoding="utf-8")
        rendered = render_projection(relative, current, state)
        if rendered != current:
            _atomic_write(path, rendered)
            changed.append(relative)
    return tuple(changed)


def _quote_toml(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def serialize_state(state: ProjectState) -> str:
    return "\n".join(
        (
            "# OnlyAlpha current engineering control state.",
            "#",
            "# This file is the sole authoring authority for the current milestone/increment",
            "# progression rendered into README.md, docs/roadmap.md and the P9.K plan.",
            "# Do not hand-edit those projections. Use scripts/project_state.py.",
            "",
            "schema_version = 1",
            "",
            "[project]",
            f"milestone = {_quote_toml(state.milestone)}",
            f"milestone_state = {_quote_toml(state.milestone_state)}",
            "",
            "[development]",
            f"last_verified_increment = {_quote_toml(state.last_verified_increment)}",
            f"last_verified_name = {_quote_toml(state.last_verified_name)}",
            f"last_verified_state = {_quote_toml(state.last_verified_state)}",
            f"active_increment = {_quote_toml(state.active_increment)}",
            f"active_name = {_quote_toml(state.active_name)}",
            f"active_state = {_quote_toml(state.active_state)}",
            f"next_authorized_increment = {_quote_toml(state.next_authorized_increment)}",
            f"next_authorized_name = {_quote_toml(state.next_authorized_name)}",
            f"next_authorized_state = {_quote_toml(state.next_authorized_state)}",
            f"p9_1_plus_status = {_quote_toml(state.p9_1_plus_status)}",
            "",
            "[certification]",
            f"latest_increment = {_quote_toml(state.latest_certified_increment)}",
            f"latest_state = {_quote_toml(state.latest_certified_state)}",
            f"latest_subject_sha = {_quote_toml(state.latest_certified_subject_sha)}",
            f"latest_run = {state.latest_certified_run}",
            f"latest_verdict = {_quote_toml(state.latest_certified_verdict)}",
            "",
        )
    )


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _commit_transition(state: ProjectState, root: Path) -> tuple[Path, ...]:
    _validate_state(state)

    projection_content: dict[Path, str] = {}
    for relative in PROJECTION_PATHS:
        path = root / relative
        projection_content[path] = render_projection(relative, path.read_text(encoding="utf-8"), state)

    authority = root / AUTHORITY_PATH
    for path, content in projection_content.items():
        _atomic_write(path, content)
    _atomic_write(authority, serialize_state(state))
    return PROJECTION_PATHS


def start_increment(state: ProjectState, increment: str) -> ProjectState:
    if state.active_increment:
        raise ProjectStateError(f"cannot start {increment}: {state.active_increment} is already active")
    if increment != state.next_authorized_increment:
        raise ProjectStateError(
            f"cannot start {increment}: next authorized increment is {state.next_authorized_increment or 'NONE'}"
        )
    return replace(
        state,
        active_increment=state.next_authorized_increment,
        active_name=state.next_authorized_name,
        active_state="IN_PROGRESS",
        next_authorized_increment="",
        next_authorized_name="",
        next_authorized_state="",
    )


def verify_increment(state: ProjectState, increment: str, *, next_id: str, next_name: str) -> ProjectState:
    if state.active_increment != increment:
        raise ProjectStateError(f"cannot verify {increment}: active increment is {state.active_increment or 'NONE'}")
    if not next_id.strip() or not next_name.strip():
        raise ProjectStateError("verification transition requires a non-empty next increment id and name")
    if next_id == increment:
        raise ProjectStateError("next authorized increment must differ from the verified increment")
    closes_p9_k = increment == "P9.K.8" and next_id.strip() == "P9.1"
    return replace(
        state,
        last_verified_increment=state.active_increment,
        last_verified_name=state.active_name,
        last_verified_state="TASK COMPLETE / VERIFIED",
        active_increment="",
        active_name="",
        active_state="",
        next_authorized_increment=next_id.strip(),
        next_authorized_name=next_name.strip(),
        next_authorized_state="IMPLEMENTATION READY",
        p9_1_plus_status=P9_K_CLOSED_STATUS if closes_p9_k else state.p9_1_plus_status,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage OnlyAlpha's canonical engineering project state")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="fail if any generated project-state projection has drifted")
    subparsers.add_parser("render", help="render current project-state authority into all projections")

    transition = subparsers.add_parser("transition", help="perform a guarded project-state transition")
    transition_subparsers = transition.add_subparsers(dest="transition_command", required=True)

    start = transition_subparsers.add_parser("start", help="start the exactly authorized next increment")
    start.add_argument("increment")

    verify = transition_subparsers.add_parser("verify", help="verify the active increment and authorize the next one")
    verify.add_argument("increment")
    verify.add_argument("--next-id", required=True)
    verify.add_argument("--next-name", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        state = load_state()
        if args.command == "check":
            drift = projection_drift(state)
            if drift:
                for path in drift:
                    print(f"PROJECT_STATE_DRIFT: {path}", file=sys.stderr)
                print("Run: uv run python scripts/project_state.py render", file=sys.stderr)
                return 1
            print("Project state authority and projections are consistent.")
            return 0

        if args.command == "render":
            changed = render_all(state)
            for path in changed:
                print(f"rendered {path}")
            if not changed:
                print("Project state projections already match authority.")
            return 0

        if args.command == "transition" and args.transition_command == "start":
            next_state = start_increment(state, args.increment)
            _commit_transition(next_state, ROOT)
            print(f"Started {args.increment}; project-state projections rendered.")
            return 0

        if args.command == "transition" and args.transition_command == "verify":
            next_state = verify_increment(
                state,
                args.increment,
                next_id=args.next_id,
                next_name=args.next_name,
            )
            _commit_transition(next_state, ROOT)
            print(f"Verified {args.increment}; authorized {args.next_id}; projections rendered.")
            return 0

        parser.error("unsupported project-state command")
    except ProjectStateError as exc:
        print(f"PROJECT_STATE_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
